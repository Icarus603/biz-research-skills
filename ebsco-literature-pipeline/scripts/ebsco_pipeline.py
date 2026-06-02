#!/usr/bin/env python3
"""
EBSCO Literature Pipeline — CLI entry point.

Connects to Chrome via CDP (requires --remote-debugging-port=9222).
Handles: VPN session → EBSCO search → PDF download → manifest.csv

Usage:
    # Start Chrome first:
    open -a "Google Chrome" --args --remote-debugging-port=9222

    # Then:
    python3 ebsco_pipeline.py search "innovation patent" \\
        --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \\
        --years 2022-2026 \\
        --output ./refs/

    python3 ebsco_pipeline.py download --manifest ./refs/manifest.csv
"""

import json
import os
import sys
import time
import csv
import base64
import tempfile
from pathlib import Path
from cdp_client import CDPClient

# ── Process lock (prevent concurrent runs on same output dir) ──────

def _atomic_write_json(path: str, data):
    """Write JSON atomically: temp file + rename. Survives crashes."""
    tmp = path + ".tmp." + str(os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)  # atomic on POSIX
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _acquire_lock(output_dir: str) -> object:
    """Acquire a file lock for the output directory.

    Writes PID + timestamp to .pipeline.lock. If a lock already exists
    and the PID is still alive, raises RuntimeError. Stale locks (dead
    PIDs) are cleaned up automatically.

    Returns a lock context that can be released via _release_lock().
    """
    lock_path = os.path.join(output_dir, ".pipeline.lock")
    os.makedirs(output_dir, exist_ok=True)

    for _ in range(3):  # retry a few times in case of race
        try:
            # Try to create lock file exclusively
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        except FileExistsError:
            # Lock file exists — check if it's stale
            try:
                with open(lock_path) as f:
                    existing = json.load(f)
                old_pid = existing.get("pid")
                if old_pid:
                    # Check if PID is alive
                    try:
                        os.kill(old_pid, 0)
                        # PID is alive — concurrent run detected
                        raise RuntimeError(
                            f"Another pipeline instance is running on this output directory "
                            f"(PID {old_pid}, since {existing.get('started','?')}). "
                            f"Wait for it to finish or remove {lock_path} manually."
                        )
                    except OSError:
                        # PID is dead — stale lock, clean it
                        print(f"[lock] Stale lock from dead PID {old_pid}, cleaning...")
                        os.unlink(lock_path)
                        continue
                else:
                    os.unlink(lock_path)
                    continue
            except RuntimeError:
                raise
            except Exception:
                os.unlink(lock_path)
                continue
        else:
            # We own the lock
            lock_data = {
                "pid": os.getpid(),
                "started": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            with os.fdopen(fd, "w") as f:
                json.dump(lock_data, f)
            return lock_path

    raise RuntimeError(f"Cannot acquire lock on {output_dir} after 3 attempts")


def _release_lock(lock_path: str):
    """Release a previously acquired lock."""
    try:
        os.unlink(lock_path)
    except OSError:
        pass


# ── VPN / EBSCO session setup ───────────────────────────────────

SETUP_SCRIPT = """
async () => {
    const URL = window.location.href;
    // Check if already on EBSCO
    if (URL.includes('research-ebsco-com') || URL.includes('research.ebsco.com')) {
        return {status: 'already_authenticated', url: URL};
    }
    // Navigate to VPN portal
    window.location.href = 'http://lib-443.webvpn.cufe.edu.cn/';
    await new Promise(r => setTimeout(r, 2000));
    window.location.href = 'https://research.ebsco.com/c/k3svp7/search';
    await new Promise(r => setTimeout(r, 3000));
    return {status: 'redirected', url: window.location.href};
}
"""


# ── Credential storage (macOS Keychain) ──────────────────────────

KEYCHAIN_SERVICE = "cufe-ebsco-pipeline"
KEYCHAIN_ACCOUNT = "cufe-sso"


def get_credentials():
    """Retrieve CUFE credentials from Keychain. Returns (username, password) or (None, None)."""
    import subprocess
    result = subprocess.run(
        ['security', 'find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w'],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, None
    lines = result.stdout.strip().split('\n')
    if len(lines) >= 2:
        return lines[0], lines[1]
    return None, None


def save_credentials(username: str, password: str):
    """Store CUFE credentials in macOS Keychain."""
    import subprocess
    data = f"{username}\n{password}"
    # Delete existing
    subprocess.run(
        ['security', 'delete-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT],
        capture_output=True
    )
    # Add new
    subprocess.run(
        ['security', 'add-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT,
         '-w', data, '-U'],
        capture_output=True
    )


def setup_session(cdp: CDPClient):
    """Establish VPN + EBSCO session. Try cookie injection first, fall back to SSO."""
    cdp._call("Network.enable", {})

    # ── Strategy 1: Cookie injection from saved session ─────────
    cookie_file = os.path.expanduser("~/.cache/ebsco-pipeline/session_cookies.json")
    if os.path.exists(cookie_file):
        print("[setup] Found saved session cookies, injecting...")
        with open(cookie_file) as f:
            cookies = json.load(f)
        ok = 0
        for key, c in cookies.items():
            try:
                cdp._call("Network.setCookie", {
                    "name": c["name"], "value": c["value"],
                    "domain": c["domain"], "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                })
                ok += 1
            except Exception:
                pass
        print(f"[setup] Injected {ok}/{len(cookies)} cookies")

        # Navigate to EBSCO and verify
        cdp._call("Page.navigate", {"url": "https://research-ebsco-com-443.webvpn.cufe.edu.cn/c/k3svp7/search"}, timeout_ms=30000)
        time.sleep(5)
        url = cdp.eval("window.location.href", await_promise=False)
        if "research-ebsco-com" in url:
            # Wait for page to fully load and verify API
            time.sleep(2)
            test = cdp.eval("""
            async () => {
                try {
                    const r = await fetch('https://research-ebsco-com-443.webvpn.cufe.edu.cn/api/search/v1/search?applyAllLimiters=true', {
                        method:'POST', headers:{'Content-Type':'application/json'},
                        body: JSON.stringify({query:'patent', profileIdentifier:'k3svp7', searchMode:'all', sort:'relevance', offset:0, count:1, userDirectAction:true, expanders:['fullText','concept']})
                    });
                    const d = await r.json();
                    return {ok: r.ok, total: d?.search?.totalItems ?? 0};
                } catch(e) { return {ok: false, error: e.message}; }
            }
            """, await_promise=True, timeout_ms=15000)
            if test.get("ok") and test.get("total", 0) > 0:
                print(f"[setup] Cookie injection OK — {test['total']} papers available.")
                return True
            else:
                print(f"[setup] Cookie API test: {test}. Trying SSO login.")

    # ── Strategy 2: Auto SSO login ─────────────────────────────
    print("[setup] SSO required. Auto-login via ~/.cufe_credentials...")

    # Read credentials from file
    cred_file = os.path.expanduser("~/.cufe_credentials")
    creds = {}
    if os.path.exists(cred_file):
        with open(cred_file) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    creds[k] = v
    username = creds.get("CUFE_USERNAME", "")
    password = creds.get("CUFE_PASSWORD", "")
    if not username or not password:
        print(f"[setup] Missing credentials in {cred_file}")
        print("        Format: CUFE_USERNAME=学号")
        print("                CUFE_PASSWORD=密码")
        return False
    print(f"[setup] Read credentials for {username}")

    # Navigate to trigger SSO
    cdp._call("Page.navigate", {"url": "https://research-ebsco-com-443.webvpn.cufe.edu.cn/c/k3svp7/search"}, timeout_ms=30000)
    time.sleep(3)
    url = cdp.eval("window.location.href", await_promise=False)

    if "research-ebsco-com" in url:
        print("[setup] Already authenticated.")
        return True

    if "authserver" not in url:
        print(f"[setup] Unexpected page: {url[:100]}")
        return False

    # Fill CAS form via JS and click the login button
    # Must click the button (not form.submit()) so encrypt.js runs
    js_fill = f"""
    (() => {{
        const u = document.querySelector('#username');
        const p = document.querySelector('#password');
        const loginBtn = document.querySelector('a[href*=\"login\"], button, input[type=submit], #loginButton');
        // Find the "登录" link
        const links = [...document.querySelectorAll('a')];
        const loginLink = links.find(a => a.textContent.trim() === '登录' && a.href.includes('javascript'));
        if (u && p) {{
            u.value = {json.dumps(username)};
            p.value = {json.dumps(password)};
            // Trigger input events so encrypt.js picks up the value
            u.dispatchEvent(new Event('input', {{bubbles: true}}));
            p.dispatchEvent(new Event('input', {{bubbles: true}}));
            if (loginLink) {{
                loginLink.click();
                return 'clicked_login_link';
            }}
            return 'filled_no_button';
        }}
        return 'no_fields';
    }})()
    """
    result = cdp.eval(js_fill, await_promise=False)
    print(f"[setup] Form fill: {result}")

    # Check if there's an error message (wrong password)
    time.sleep(2)
    page_text = cdp.eval("document.body.innerText.slice(0, 200)", await_promise=False)
    if "密码有误" in (page_text or ""):
        print("[setup] Wrong password. Check ~/.cufe_credentials")
        return False
    if "用户名或者密码有误" in (page_text or ""):
        print("[setup] Wrong username or password.")
        return False

    # Wait for redirect through CAS → VPN → EBSCO
    for i in range(20):
        time.sleep(2)
        url = cdp.eval("window.location.href", await_promise=False)
        if "research-ebsco-com" in url:
            print("[setup] Auto-login successful!")
            _save_cookies(cdp, cookie_file)
            return True
        if "webvpn.cufe.edu.cn" in url and "authserver" not in url:
            cdp._call("Page.navigate", {"url": "https://research-ebsco-com-443.webvpn.cufe.edu.cn/c/k3svp7/search"}, timeout_ms=30000)

    print("[setup] Auto-login timed out.")
    return False


def _save_cookies(cdp: CDPClient, cookie_file: str):
    """Extract cookies via CDP and save to file for future auto-login."""
    domains = [
        "https://webvpn.cufe.edu.cn",
        "https://research-ebsco-com-443.webvpn.cufe.edu.cn",
        "https://research.ebsco.com",
        "https://authserver.cufe.edu.cn",
    ]
    all_cookies = {}
    for domain in domains:
        try:
            result = cdp._call("Network.getCookies", {"urls": [domain]})
            for c in result.get("result", {}).get("cookies", []):
                key = f"{c['domain']}|{c['name']}"
                all_cookies[key] = {
                    "name": c["name"], "value": c["value"],
                    "domain": c["domain"], "path": c.get("path", "/"),
                    "httpOnly": c.get("httpOnly", False),
                    "secure": c.get("secure", False),
                    "expires": c.get("expires", 0),
                }
        except Exception as e:
            print(f"  [warn] getCookies {domain}: {e}")
    os.makedirs(os.path.dirname(cookie_file), exist_ok=True)
    _atomic_write_json(cookie_file, all_cookies)
    print(f"[setup] Saved {len(all_cookies)} cookies to {cookie_file}")


# ── Search JS (runs in browser via CDP) ─────────────────────────

def build_search_js(query: str, journals: list[str], years: str, max_count: int = 500) -> str:
    """Build the bundled JavaScript for EBSCO search."""
    so_clause = " OR ".join(f'SO "{j}"' for j in journals)
    q = f"({so_clause}) AND ({query}) AND DT {years}"
    print(f"[search] Built query: {q[:200]}...")

    # Use a template file to avoid Python f-string brace hell
    js_template = '''async () => {
    const BASE = 'https://research-ebsco-com-443.webvpn.cufe.edu.cn';
    const API = BASE + '/api/search/v1/search?applyAllLimiters=true';
    const QUERY = __QUERY__;
    const MAX = __MAX__;

    const allPapers = [];
    const seen = new Set();
    let offset = 0;
    const PER_PAGE = 50;
    let dbTotal = 0;

    while (allPapers.length < MAX) {
        const resp = await fetch(API, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                query: QUERY,
                profileIdentifier: 'k3svp7',
                searchMode: 'all',
                sort: 'relevance',
                offset: offset,
                count: PER_PAGE,
                userDirectAction: true,
                expanders: ['fullText', 'concept']
            })
        });
        const data = await resp.json();
        const items = data?.search?.items || [];
        dbTotal = data?.search?.totalItems ?? dbTotal;

        for (const item of items) {
            const doi = item.doi || null;
            const key = doi || item.an || item.id;
            if (seen.has(key)) continue;
            seen.add(key);

            const title = typeof item.title === 'string' ? item.title : (item.title?.value || 'Unknown');
            const firstAuthor = item.contributors?.[0]?.name?.split(',')[0]?.trim() || 'Unknown';
            const source = item.source || '';
            const year = (item.publicationDate || item.coverDate || '').slice(0, 4);
            const hasPDF = item.links?.downloadLinks?.some(l => l.type === 'pdf') || false;
            const pdfUrl = hasPDF
                ? BASE + '/api/search/v1/record/' + item.id + '/fulltext/pdf?sourceRecordId=' + item.id + '&opid=k3svp7&intent=download'
                : null;

            allPapers.push({
                title, first_author: firstAuthor,
                year: parseInt(year) || null,
                venue: source,
                doi,
                ebsco_id: item.id,
                pdf_url: pdfUrl,
                has_pdf: hasPDF,
                peer_reviewed: item.peerReviewed || false,
                abstract: typeof item.abstract === 'string' ? item.abstract?.slice(0, 500) : (item.abstract?.value?.slice(0, 500) || '')
            });
        }

        offset += PER_PAGE;
        if (items.length < PER_PAGE || (dbTotal > 0 && offset >= dbTotal)) break;
        await new Promise(r => setTimeout(r, 300));
    }

    return {
        total_found: allPapers.length,
        db_total: dbTotal,
        query: QUERY,
        papers: allPapers
    };
}'''
    return js_template.replace('__QUERY__', json.dumps(q)).replace('__MAX__', str(max_count))


def search(cdp: CDPClient, query: str, journals: list[str], years: str,
            max_count: int = 500, output_dir: str = "."):
    """Run EBSCO search and save results."""
    print(f"[search] Query: {query}")
    print(f"[search] Journals: {journals}")
    print(f"[search] Date range: {years}")

    js = build_search_js(query, journals, years, max_count)
    print(f"[search] Running search (max {max_count} papers)...")

    result = cdp.eval(js, await_promise=True, timeout_ms=300_000)
    papers = result.get("papers", [])
    raw_count = len(papers)

    # Filter to exact journal matches (EBSCO SO field does substring matching)
    if journals:
        def _norm(v):
            return v.strip().lower().replace('&amp;', '&').replace('.', '').replace('  ', ' ')
        journal_norms = {_norm(j) for j in journals}
        filtered = []
        rejected = []
        for p in papers:
            vn = _norm(p.get("venue", ""))
            if vn in journal_norms:
                filtered.append(p)
            else:
                rejected.append(vn)
        if rejected:
            from collections import Counter
            rc = Counter(rejected)
            print(f"[search] Filtered out {len(papers)-len(filtered)} non-matching papers ({len(rc)} other journals)")
        papers = filtered

    # Assign idx for later download reference
    for i, p in enumerate(papers, 1):
        p["idx"] = i
    print(f"[search] Found {raw_count} raw, {len(papers)} after journal filter")

    # Save JSON
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "papers.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    print(f"[search] Saved to {json_path}")

    # Generate manifest.csv
    manifest_path = os.path.join(output_dir, "manifest.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "year", "first_author", "title", "venue", "doi", "has_pdf", "source"])
        for i, p in enumerate(papers, 1):
            w.writerow([f"{i:03d}", p["year"], p["first_author"], p["title"], p["venue"], p.get("doi", ""), p["has_pdf"], "ebsco"])
    print(f"[search] Manifest: {manifest_path}")

    return papers


# ── PDF Download ────────────────────────────────────────────────

def _paper_filename(paper: dict) -> str:
    """Build a safe filename for a paper: FirstAuthor_Year_Title.pdf"""
    import html as _html
    title = (paper.get('title', '') or 'unknown')
    # Decode HTML entities (&amp; → &, &lt; → <, etc.)
    title = _html.unescape(title)
    title_slug = "".join(c if c.isalnum() or c in " _-" else "" for c in title[:60]).strip().replace(" ", "_")[:60]
    name = f"{paper.get('first_author','unknown')}_{paper.get('year','')}_{title_slug}"
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:120] + ".pdf"


def _download_chunk_js(chunk_items: list) -> str:
    """Build JS that fetches PDFs as blobs and returns them as base64 data URLs.

    Returns data to Python via CDP eval result — no Chrome download manager needed.
    Each result has {name, idx, ok, size, data} where data is a 'data:application/pdf;base64,...' URL.
    """
    return """async () => {
    const items = """ + json.dumps(chunk_items) + """;
    const CONCURRENCY = 10;
    const results = [];
    for (let i = 0; i < items.length; i += CONCURRENCY) {
        const sub = items.slice(i, i + CONCURRENCY);
        const fetched = await Promise.all(sub.map(async (item) => {
            try {
                const resp = await fetch(item.url);
                if (!resp.ok) return Object.assign({}, item, {error: 'HTTP '+resp.status});
                const ct = resp.headers.get('content-type') || '';
                if (!ct.includes('pdf')) return Object.assign({}, item, {error: 'not PDF: '+ct});
                const blob = await resp.blob();
                const dataUrl = await new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = () => reject(reader.error);
                    reader.readAsDataURL(blob);
                });
                return Object.assign({}, item, {ok: true, size: blob.size, data: dataUrl});
            } catch(e) {
                return Object.assign({}, item, {error: e.message || String(e)});
            }
        }));
        for (const f of fetched) {
            if (f.ok) {
                results.push({idx: f.idx, ok: true, size: f.size, name: f.name, data: f.data});
            } else {
                results.push({idx: f.idx, ok: false, error: f.error, name: f.name});
            }
        }
    }
    return results;
}"""


def download_pdfs(cdp: CDPClient, manifest_path: str, output_dir: str = ".", chunk_size: int = 15, retry_count: int = 1):
    """Download PDFs for papers with pdf_url.

    Acquires a process lock on the output directory BEFORE any file I/O.
    """
    abs_output = os.path.abspath(output_dir)
    os.makedirs(abs_output, exist_ok=True)
    print(f"[download] Output dir: {abs_output}")

    # ── Acquire process lock FIRST, before any file reads ──────────
    lock_path = _acquire_lock(abs_output)
    print(f"[download] Lock acquired (PID {os.getpid()})")

    try:
        json_path = manifest_path.replace(".csv", ".json") if manifest_path.endswith(".csv") else manifest_path
        if not os.path.exists(json_path):
            alt = os.path.join(os.path.dirname(json_path), "papers.json")
            if os.path.exists(alt):
                json_path = alt
        with open(json_path) as f:
            papers = json.load(f)

        pdf_papers = [p for p in papers if p.get("pdf_url")]
        total = len(pdf_papers)
        print(f"[download] {total}/{len(papers)} papers have PDF links")

        if total == 0:
            print("[download] No PDFs to download.")
            return 0
        # ── DOI-based dedup ────────────────────────────────────────────
        # Load downloaded.json sidecar: {doi: filename}. Survives filename format changes.
        sidecar_path = os.path.join(abs_output, "downloaded.json")
        if os.path.exists(sidecar_path):
            with open(sidecar_path) as f:
                downloaded_map = json.load(f)
        else:
            downloaded_map = {}

        # Also reconcile with actual files on disk
        actual_files = set(f for f in os.listdir(abs_output) if f.endswith('.pdf') and f != "downloaded.json")
        # Files on disk not in sidecar → add by filename (best-effort, no DOI)
        for fname in actual_files:
            if fname not in downloaded_map.values():
                downloaded_map[f"file:{fname}"] = fname

        pending = []
        skipped = 0
        for p in pdf_papers:
            doi = (p.get("doi") or "").strip().lower()
            fname = _paper_filename(p)
            # Check by DOI first, then by filename
            if doi and doi in downloaded_map:
                # Verify file still exists; if not, re-download
                if os.path.exists(os.path.join(abs_output, downloaded_map[doi])):
                    skipped += 1
                    continue
                else:
                    del downloaded_map[doi]
            if fname in downloaded_map.values():
                skipped += 1
                continue
            pending.append(p)

        if skipped > 0:
            print(f"[download] {skipped}/{total} already downloaded, {len(pending)} remaining")

        if not pending:
            print("[download] All PDFs already downloaded.")
            return len(pdf_papers)

        # Build chunk items for all pending papers
        pending_dois = {}  # idx → doi for sidecar recording
        all_items = []
        for i, p in enumerate(pending):
            name = _paper_filename(p)
            doi = (p.get("doi") or "").strip().lower()
            all_items.append({"url": p["pdf_url"], "name": name, "idx": i + 1, "doi": doi})
            if doi:
                pending_dois[i + 1] = doi

        # Process in chunks
        chunks = [all_items[i:i + chunk_size] for i in range(0, len(all_items), chunk_size)]
        total_ok = skipped
        total_fail = 0
        retry_queue: list[dict] = []  # items to retry individually
        chunk_timeout_ms = max(120_000, chunk_size * 15_000)

        for ci, chunk in enumerate(chunks):
            chunk_start = ci * chunk_size + 1
            chunk_end = chunk_start + len(chunk) - 1
            print(f"[download] Chunk {ci+1}/{len(chunks)} (papers {chunk_start}-{chunk_end}, {len(chunk)} PDFs)...")

            # ── Health check before each chunk ──────────────────────
            if not cdp.ping():
                print("[download] CDP connection lost. Attempting reconnect...")
                try:
                    cdp.reconnect()
                    time.sleep(2)
                    # Re-establish EBSCO session after reconnect
                    # Cookie injection should still work since cookies persist
                    cdp._call("Network.enable", {})
                    cookie_file = os.path.expanduser("~/.cache/ebsco-pipeline/session_cookies.json")
                    if os.path.exists(cookie_file):
                        with open(cookie_file) as f:
                            cookies = json.load(f)
                        for key, c in cookies.items():
                            try:
                                cdp._call("Network.setCookie", {
                                    "name": c["name"], "value": c["value"],
                                    "domain": c["domain"], "path": c.get("path", "/"),
                                    "httpOnly": c.get("httpOnly", False),
                                    "secure": c.get("secure", False),
                                })
                            except Exception:
                                pass
                        # Navigate back to EBSCO
                        cdp._call("Page.navigate", {"url": "https://research-ebsco-com-443.webvpn.cufe.edu.cn/c/k3svp7/search"}, timeout_ms=30000)
                        time.sleep(3)
                    print("[download] Reconnected.")
                except Exception as e:
                    print(f"[download] Reconnect failed: {e}")
                    # Queue chunk for retry
                    for item in chunk:
                        retry_queue.append({**item, "_last_error": f"CDP reconnect failed: {e}"})
                    continue

            js = _download_chunk_js(chunk)
            try:
                results = cdp.eval(js, await_promise=True, timeout_ms=chunk_timeout_ms)
            except Exception as e:
                print(f"[download] Chunk {ci+1} eval failed: {e}")
                # Queue entire chunk for retry (timeout / network errors are transient)
                for item in chunk:
                    retry_queue.append({**item, "_last_error": str(e)})
                continue

            chunk_ok = 0
            for r in (results or []):
                if r.get("ok") and r.get("data"):
                    try:
                        data_url = r["data"]
                        b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
                        pdf_bytes = base64.b64decode(b64)
                        fpath = os.path.join(abs_output, r["name"])
                        with open(fpath, "wb") as fout:
                            fout.write(pdf_bytes)
                        size_kb = len(pdf_bytes) // 1024
                        chunk_ok += 1
                        # Record DOI → filename for future dedup
                        doi = pending_dois.get(r["idx"])
                        if doi:
                            downloaded_map[doi] = r["name"]
                        else:
                            downloaded_map[f"file:{r['name']}"] = r["name"]
                        print(f"[download]   {r['idx']}/{len(all_items)}: {r['name']} ({size_kb}KB)")
                    except Exception as e:
                        total_fail += 1
                        print(f"[download]   {r['idx']}/{len(all_items)}: DECODE_ERR {r['name']} - {e}")
                else:
                    err = r.get("error", "?")
                    # HTTP 400 = permanent, don't retry
                    if "HTTP 400" in str(err):
                        total_fail += 1
                        print(f"[download]   {r['idx']}/{len(all_items)}: SKIP {r['name']} - {err} (permanent)")
                    else:
                        retry_queue.append({"url": r.get("url", ""), "name": r["name"], "idx": r["idx"], "doi": pending_dois.get(r["idx"], ""), "_last_error": str(err)})
                        print(f"[download]   {r['idx']}/{len(all_items)}: FAIL {r['name']} - {err} (will retry)")

            total_ok += chunk_ok
            # Save sidecar after each chunk (atomic write)
            _atomic_write_json(sidecar_path, downloaded_map)

        # ── Retry phase ───────────────────────────────────────────────
        if retry_queue and retry_count > 0:
            print(f"\n[download] Retry phase: {len(retry_queue)} papers, {retry_count} attempt(s)...")
            for attempt in range(1, retry_count + 1):
                if not retry_queue:
                    break
                print(f"[download] Retry attempt {attempt}/{retry_count} ({len(retry_queue)} papers)...")
                still_failed = []
                # Retry one at a time for reliability
                for item in retry_queue:
                    # Health check before each retry
                    if not cdp.ping():
                        try:
                            cdp.reconnect()
                            time.sleep(1)
                        except Exception:
                            still_failed.append({**item, "_last_error": "CDP dead during retry"})
                            continue

                    js = _download_chunk_js([item])
                    try:
                        results = cdp.eval(js, await_promise=True, timeout_ms=60_000)
                    except Exception as e:
                        still_failed.append({**item, "_last_error": str(e)})
                        print(f"[download]   RETRY {item['idx']}: {item['name']} - eval error: {e}")
                        continue

                    r = (results or [{}])[0]
                    if r.get("ok") and r.get("data"):
                        try:
                            data_url = r["data"]
                            b64 = data_url.split(",", 1)[1] if "," in data_url else data_url
                            pdf_bytes = base64.b64decode(b64)
                            fpath = os.path.join(abs_output, item["name"])
                            with open(fpath, "wb") as fout:
                                fout.write(pdf_bytes)
                            size_kb = len(pdf_bytes) // 1024
                            total_ok += 1
                            doi = item.get("doi", "")
                            if doi:
                                downloaded_map[doi] = item["name"]
                            print(f"[download]   RETRY {item['idx']}: OK {item['name']} ({size_kb}KB)")
                        except Exception as e:
                            still_failed.append(item)
                            print(f"[download]   RETRY {item['idx']}: DECODE_ERR {item['name']} - {e}")
                    else:
                        err = r.get("error", "?")
                        if "HTTP 400" in str(err):
                            total_fail += 1
                            print(f"[download]   RETRY {item['idx']}: SKIP {item['name']} - {err} (permanent)")
                        elif attempt == retry_count:
                            total_fail += 1
                            still_failed.append(item)
                            print(f"[download]   RETRY {item['idx']}: FAIL {item['name']} - {err} (exhausted)")
                        else:
                            still_failed.append({**item, "_last_error": str(err)})
                            print(f"[download]   RETRY {item['idx']}: STILL {item['name']} - {err}")

                retry_queue = still_failed
                if retry_queue:
                    _atomic_write_json(sidecar_path, downloaded_map)

            # Any left in retry_queue after all attempts = permanent failure
            total_fail += len(retry_queue)
            if retry_queue:
                print(f"[download] {len(retry_queue)} papers failed after {retry_count} retries")

        # Save final sidecar (atomic write)
        _atomic_write_json(sidecar_path, downloaded_map)

        final_count = len([f for f in os.listdir(abs_output) if f.endswith('.pdf')])
        print(f"[download] Done. {final_count} PDFs on disk ({total_fail} failed, {total_ok} OK)")
        return total_ok

    finally:
        _release_lock(lock_path)


# ── CLI ──────────────────────────────────────────────────────────

def ensure_chrome(port: int = 9222, profile_dir: str = None):
    """Ensure Chrome is running with remote debugging on the given port.

    Checks if an existing Chrome on this port is healthy (has pages available).
    If no pages or Chrome is unresponsive, kills it and starts fresh.
    Uses a dedicated profile so it never conflicts with the user's normal Chrome.
    """
    import subprocess as _sp
    import urllib.request

    def _chrome_alive():
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
            return True
        except Exception:
            return False

    def _has_pages():
        try:
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3)
            pages = json.loads(resp.read())
            return any(p.get("type") == "page" for p in pages)
        except Exception:
            return False

    # Check existing Chrome
    if _chrome_alive():
        if _has_pages():
            print(f"[chrome] Chrome already running on port {port} (healthy)")
            return
        else:
            # Chrome is alive but has no pages — kill and restart
            print("[chrome] Chrome running but no pages. Restarting...")
            try:
                # Find and kill the Chrome process on this port
                result = _sp.run(
                    ["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True
                )
                for pid_str in result.stdout.strip().split("\n"):
                    if pid_str:
                        try:
                            os.kill(int(pid_str), 9)
                        except OSError:
                            pass
            except Exception:
                pass
            time.sleep(2)

    # Start Chrome
    if profile_dir is None:
        profile_dir = os.path.expanduser("~/.cache/ebsco-pipeline/chrome-profile")
    os.makedirs(profile_dir, exist_ok=True)
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        for p in ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]:
            if os.path.exists(p):
                chrome_path = p
                break
    print(f"[chrome] Starting Chrome on port {port}...")
    _sp.Popen([chrome_path, f"--remote-debugging-port={port}",
               f"--user-data-dir={profile_dir}",
               "--headless=new",
               "--no-first-run", "--no-default-browser-check"],
              stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    time.sleep(4)

    # Ensure at least one page is open by navigating to about:blank
    try:
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/new?about:blank", timeout=5)
        resp.read()
        time.sleep(0.5)
    except Exception:
        pass

    print("[chrome] Chrome ready.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="EBSCO Literature Pipeline")
    sub = parser.add_subparsers(dest="command")

    # search subcommand
    sp = sub.add_parser("search")
    sp.add_argument("query", help="Search query (e.g., 'innovation OR patent OR R&D')")
    sp.add_argument("--journals", default="", help="Comma-separated journal names")
    sp.add_argument("--years", default="2022-2026", help="Date range")
    sp.add_argument("--max", type=int, default=500, help="Max papers to retrieve")
    sp.add_argument("--output", "-o", default="./refs", help="Output directory")

    # download subcommand
    dp = sub.add_parser("download")
    dp.add_argument("--manifest", required=True, help="Path to papers.json or manifest.csv")
    dp.add_argument("--output", "-o", default=None, help="Output directory for PDFs (default: <manifest_dir>/pdfs/)")
    dp.add_argument("--chunk-size", type=int, default=15, help="PDFs per chunk (default 15)")
    dp.add_argument("--retry", type=int, default=1, help="Retry count for transient failures (default 1)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Auto-start Chrome if needed
    ensure_chrome()

    cdp = CDPClient()
    try:
        # Retry connect in case Chrome needs a moment to create pages
        for retry in range(3):
            try:
                cdp.connect()
                break
            except RuntimeError as e:
                if "No page found" in str(e) and retry < 2:
                    import urllib.request
                    try:
                        urllib.request.urlopen(f"http://127.0.0.1:9222/json/new?about:blank", timeout=3)
                    except Exception:
                        pass
                    time.sleep(2)
                    print(f"[main] Retrying connect ({retry+2}/3)...")
                else:
                    raise

        if args.command == "search":
            journals = [j.strip() for j in args.journals.split(",") if j.strip()]
            # Use pre-set journal lists if name given
            if not journals:
                print("Warning: No --journals specified. Searching all sources.")
            setup_session(cdp)
            search(cdp, args.query, journals, args.years, args.max, args.output)

        elif args.command == "download":
            setup_session(cdp)
            output_dir = args.output
            if output_dir is None:
                # Auto-derive: <manifest_dir>/pdfs/
                manifest_dir = os.path.dirname(os.path.abspath(args.manifest))
                output_dir = os.path.join(manifest_dir, "pdfs")
            download_pdfs(cdp, args.manifest, output_dir, args.chunk_size, args.retry)

    finally:
        cdp.close()


if __name__ == "__main__":
    main()
