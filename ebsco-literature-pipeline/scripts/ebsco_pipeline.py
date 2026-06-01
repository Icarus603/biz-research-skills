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
        --output ./papers/

    python3 ebsco_pipeline.py download --manifest ./papers/manifest.csv
"""

import json
import os
import sys
import time
import csv
from pathlib import Path
from cdp_client import CDPClient

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
    with open(cookie_file, "w") as f:
        json.dump(all_cookies, f, indent=2, ensure_ascii=False)
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
    # Assign idx for later download reference
    for i, p in enumerate(papers, 1):
        p["idx"] = i
    print(f"[search] Found {len(papers)} papers")

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

def download_pdfs(cdp: CDPClient, manifest_path: str, output_dir: str = "."):
    """Download PDFs for papers with pdf_url. Uses fetch+blob+download approach."""
    json_path = manifest_path.replace(".csv", ".json") if manifest_path.endswith(".csv") else manifest_path
    with open(json_path) as f:
        papers = json.load(f)

    pdf_papers = [p for p in papers if p.get("pdf_url")]
    print(f"[download] {len(pdf_papers)}/{len(papers)} papers have PDF links")

    os.makedirs(output_dir, exist_ok=True)

    # Allow multiple downloads without prompting
    abs_output = os.path.abspath(output_dir)
    cdp._call("Browser.setDownloadBehavior", {
        "behavior": "allowAndName",
        "downloadPath": abs_output,
        "eventsEnabled": True
    })
    print(f"[download] Download dir: {abs_output}")

    # PARALLEL download: Promise.all fetch -> trigger all <a download> at once
    ok_count = 0
    fail_count = 0
    total = len(pdf_papers)

    # Build items array for JS
    items_for_js = []
    for i, p in enumerate(pdf_papers):
        title_slug = "".join(c if c.isalnum() or c in " _-" else "" for c in (p.get('title','') or 'unknown')[:60]).strip().replace(" ", "_")[:60]
        name = f"{p.get('first_author','unknown')}_{p.get('year','')}_{title_slug}"
        name = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)[:120]
        items_for_js.append({"url": p["pdf_url"], "name": name + ".pdf", "idx": i + 1})

    js = json.dumps("""
async () => {
    const items = __ITEMS__;
    // Phase 1: fetch ALL in parallel
    const fetched = await Promise.all(items.map(async (item) => {
        try {
            const resp = await fetch(item.url);
            if (!resp.ok) return {...item, error: 'HTTP '+resp.status};
            const ct = resp.headers.get('content-type') || '';
            if (!ct.includes('pdf')) return {...item, error: 'not PDF: '+ct.slice(0,50)};
            const blob = await resp.blob();
            const blobUrl = URL.createObjectURL(blob);
            return {...item, blobUrl, size: blob.size, ok: true};
        } catch(e) {
            return {...item, error: e.message};
        }
    }));
    // Phase 2: trigger all downloads
    const results = [];
    for (const f of fetched) {
        if (f.blobUrl) {
            const a = document.createElement('a');
            a.href = f.blobUrl;
            a.download = f.name;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(f.blobUrl), 10000);
            results.push({idx: f.idx, ok: true, size: f.size, name: f.name});
        } else {
            results.push({idx: f.idx, ok: false, error: f.error, name: f.name});
        }
    }
    return results;
}
""".replace("__ITEMS__", json.dumps(items_for_js)))

    # Remove outer json.dumps wrapping to get clean JS string
    js = js.replace('"async () => {', 'async () => {').replace('}"', '}').replace('\\n', '\n').replace('\\"', '"').replace('\\\\', '\\')
    # Actually let me just build it properly

    js2 = """async () => {
    const items = """ + json.dumps(items_for_js) + """;
    const fetched = await Promise.all(items.map(async (item) => {
        try {
            const resp = await fetch(item.url);
            if (!resp.ok) return Object.assign({}, item, {error: 'HTTP '+resp.status});
            const ct = resp.headers.get('content-type') || '';
            if (!ct.includes('pdf')) return Object.assign({}, item, {error: 'not PDF'});
            const blob = await resp.blob();
            const blobUrl = URL.createObjectURL(blob);
            return Object.assign({}, item, {blobUrl, size: blob.size, ok: true});
        } catch(e) {
            return Object.assign({}, item, {error: e.message});
        }
    }));
    const results = [];
    for (const f of fetched) {
        if (f.blobUrl) {
            const a = document.createElement('a');
            a.href = f.blobUrl;
            a.download = f.name;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(function() { URL.revokeObjectURL(f.blobUrl); }, 10000);
            results.push({idx: f.idx, ok: true, size: f.size, name: f.name});
        } else {
            results.push({idx: f.idx, ok: false, error: f.error, name: f.name});
        }
    }
    return results;
}"""

    results = cdp.eval(js2, await_promise=True, timeout_ms=300000)

    download_names = {}
    for r in (results or []):
        if r.get("ok"):
            ok_count += 1
            download_names[r['idx']] = r['name']
            print(f"[download] {r['idx']}/{total}: {r['name']} ({r.get('size',0)//1024}KB)")
        else:
            fail_count += 1
            print(f"[download] {r['idx']}/{total}: SKIP {r['name']} - {r.get('error','?')}")

    # Move downloaded PDFs from ~/Downloads/ to output dir using exact JS filenames
    if ok_count > 0:
        dl_dir = os.path.expanduser("~/Downloads")
        moved = 0
        for name in download_names.values():
            src = os.path.join(dl_dir, name)
            if os.path.exists(src):
                os.rename(src, os.path.join(abs_output, name))
                moved += 1
        if moved > 0:
            print(f"[download] Moved {moved}/{ok_count} PDFs to {abs_output}/")

    return ok_count


# ── CLI ──────────────────────────────────────────────────────────

def ensure_chrome(port: int = 9222, profile_dir: str = None):
    """Ensure Chrome is running with remote debugging on the given port."""
    import subprocess as _sp
    # Check if Chrome debug port is already available
    try:
        import urllib.request
        urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2)
        print(f"[chrome] Chrome already running on port {port}")
        return
    except Exception:
        pass

    # Start Chrome
    if profile_dir is None:
        profile_dir = os.path.expanduser("~/.cache/ebsco-pipeline/chrome-profile")
    os.makedirs(profile_dir, exist_ok=True)
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        # Try other common paths
        for p in ["/usr/bin/google-chrome", "/usr/bin/chromium-browser", "/usr/bin/chromium"]:
            if os.path.exists(p):
                chrome_path = p
                break
    print(f"[chrome] Starting Chrome on port {port}...")
    _sp.Popen([chrome_path, f"--remote-debugging-port={port}",
               f"--user-data-dir={profile_dir}",
               "--no-first-run", "--no-default-browser-check"],
              stdout=_sp.DEVNULL, stderr=_sp.DEVNULL)
    time.sleep(4)
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
    sp.add_argument("--output", "-o", default="./papers", help="Output directory")

    # download subcommand
    dp = sub.add_parser("download")
    dp.add_argument("--manifest", required=True, help="Path to papers.json or manifest.csv")
    dp.add_argument("--output", "-o", default="./papers", help="Output directory for PDFs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Auto-start Chrome if needed
    ensure_chrome()

    cdp = CDPClient()
    try:
        cdp.connect()

        if args.command == "search":
            journals = [j.strip() for j in args.journals.split(",") if j.strip()]
            # Use pre-set journal lists if name given
            if not journals:
                print("Warning: No --journals specified. Searching all sources.")
            setup_session(cdp)
            search(cdp, args.query, journals, args.years, args.max, args.output)

        elif args.command == "download":
            setup_session(cdp)
            download_pdfs(cdp, args.manifest, args.output)

    finally:
        cdp.close()


if __name__ == "__main__":
    main()
