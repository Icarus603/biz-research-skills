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

EBSCO_PROFILES = {
    "all": "k3svp7",      # EBSCO-ALL: broad, noisy; best for resolve/download fallback
    "bsc": "4s3yq5",      # Business Source Complete: cleaner for business/econ discovery
    "general": "cojp6y",  # General institutional profile
}

# Facet/database filters confirmed against POST /api/search/v1/search.
# Only the request-body key `filters` works; facetFilters/appliedFacets/databaseIds do not.
DATABASE_FILTERS = {
    "econ": ["eoh", "bth", "edb"],  # EconLit with Full Text, Business Source Complete, Complementary Index
    "bsc": ["bth"],
    "econlit": ["eoh"],
    "none": [],
}

SOURCE_TYPE_FILTERS = {
    "academic": ["160MN"],
    "none": [],
}


def _norm_facet_value(value: str) -> str:
    """Normalize values for EBSCO facet filters (Journal facet expects lowercase labels)."""
    return value.strip().lower()


def _build_filters(journals: list[str], database_scope: str, source_type_scope: str,
                   use_journal_filter: bool = True) -> list[dict]:
    filters = []
    db_values = DATABASE_FILTERS.get(database_scope)
    if db_values is None:
        raise ValueError(f"Unknown database scope: {database_scope}. Choose: {', '.join(DATABASE_FILTERS)}")
    if db_values:
        filters.append({"id": "databases", "values": db_values})

    st_values = SOURCE_TYPE_FILTERS.get(source_type_scope)
    if st_values is None:
        raise ValueError(f"Unknown source type scope: {source_type_scope}. Choose: {', '.join(SOURCE_TYPE_FILTERS)}")
    if st_values:
        filters.append({"id": "sourceTypes", "values": st_values})

    if use_journal_filter and journals:
        filters.append({"id": "Journal", "values": [_norm_facet_value(j) for j in journals]})

    return filters


def build_search_js(query: str, journals: list[str], years: str, max_count: int = 500,
                    full_text_only: bool = False, peer_reviewed_only: bool = False,
                    profile: str = "bsc", database_scope: str = "econ",
                    source_type_scope: str = "academic", use_so_query: bool = False,
                    use_journal_filter: bool = True) -> str:
    """Build the bundled JavaScript for EBSCO search."""
    clauses = []
    if use_so_query and journals:
        so_clause = " OR ".join(f'SO "{j}"' for j in journals)
        clauses.append(f"({so_clause})")
    clauses.append(f"({query})")
    clauses.append(f"DT {years}")
    q = " AND ".join(clauses)
    if full_text_only:
        q = f"({q}) AND FT y"
    if peer_reviewed_only:
        q = f"({q}) AND RV y"

    profile_id = EBSCO_PROFILES.get(profile, profile)
    filters = _build_filters(journals, database_scope, source_type_scope, use_journal_filter)
    print(f"[search] Built query: {q[:200]}...")
    print(f"[search] API profile: {profile} ({profile_id})")
    print(f"[search] API filters: {filters or 'none'}")

    # Use a template file to avoid Python f-string brace hell
    js_template = '''async () => {
    const BASE = 'https://research-ebsco-com-443.webvpn.cufe.edu.cn';
    const API = BASE + '/api/search/v1/search?applyAllLimiters=true';
    const QUERY = __QUERY__;
    const MAX = __MAX__;
    const PROFILE = __PROFILE__;
    const FILTERS = __FILTERS__;

    const allPapers = [];
    const seen = new Set();
    let offset = 0;
    const PER_PAGE = 50;
    let dbTotal = 0;
    let facets = null;

    while (allPapers.length < MAX) {
        const resp = await fetch(API, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                query: QUERY,
                profileIdentifier: PROFILE,
                searchMode: 'all',
                sort: 'relevance',
                offset: offset,
                count: PER_PAGE,
                userDirectAction: true,
                expanders: ['fullText', 'concept'],
                filters: FILTERS
            })
        });
        const data = await resp.json();
        const items = data?.search?.items || [];
        dbTotal = data?.search?.totalItems ?? dbTotal;

        // Capture facets from first page
        if (!facets && data?.search?.facets) {
            facets = data.search.facets.map(f => ({
                id: f.id,
                label: f.label,
                values: (f.values || []).map(v => ({value: v.value, count: v.count}))
            }));
        }

        for (const item of items) {
            if (allPapers.length >= MAX) break;
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
                ? BASE + '/api/search/v1/record/' + item.id + '/fulltext/pdf?sourceRecordId=' + item.id + '&opid=' + PROFILE + '&intent=download'
                : null;

            // Extract subjects (DE = descriptors/keywords)
            const subjects = (item.subjects || []).map(s =>
                typeof s.name === 'string' ? s.name : (s.name?.value || '')
            ).filter(Boolean);

            allPapers.push({
                title, first_author: firstAuthor,
                year: parseInt(year) || null,
                venue: source,
                doi,
                ebsco_id: item.id,
                pdf_url: pdfUrl,
                has_pdf: hasPDF,
                peer_reviewed: item.peerReviewed || false,
                doc_types: item.docTypes || [],
                subjects: subjects,
                page_count: item.pageCount || null,
                publisher: item.publisherName || null,
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
        facets: facets,
        query: QUERY,
        papers: allPapers
    };
}'''
    return (js_template
            .replace('__QUERY__', json.dumps(q))
            .replace('__MAX__', str(max_count))
            .replace('__PROFILE__', json.dumps(profile_id))
            .replace('__FILTERS__', json.dumps(filters)))


def cmd_status(directory: str = "./refs"):
    """Print summary of existing content in a project directory. No Chrome needed."""
    import glob as _glob
    d = os.path.abspath(directory)
    print(f"[status] Checking {d}")
    if not os.path.isdir(d):
        print(f"[status] Directory does not exist — nothing collected yet.")
        return

    # papers.json
    json_path = os.path.join(d, "papers.json")
    papers = []
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            papers = json.load(f)
        years_set = sorted(set(str(p.get("year", "?")) for p in papers if p.get("year")))
        venues = {}
        has_pdf_count = 0
        for p in papers:
            v = p.get("venue", "?")
            venues[v] = venues.get(v, 0) + 1
            if p.get("has_pdf"):
                has_pdf_count += 1
        print(f"[status] papers.json: {len(papers)} papers, {has_pdf_count} with PDF links")
        print(f"[status]   Years: {years_set[0]}–{years_set[-1]}" if years_set else "[status]   Years: ?")
        print(f"[status]   Venues: {', '.join(f'{v}({c})' for v, c in sorted(venues.items(), key=lambda x: -x[1]))}")
    else:
        print(f"[status] papers.json: not found (no search results yet)")

    # pdfs/
    pdf_dir = os.path.join(d, "pdfs")
    if os.path.isdir(pdf_dir):
        pdfs = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
        total_size = sum(os.path.getsize(os.path.join(pdf_dir, f)) for f in pdfs)
        size_mb = total_size / (1024 * 1024)
        print(f"[status] pdfs/: {len(pdfs)} PDFs ({size_mb:.1f} MB)")

        # downloaded.json sidecar
        sidecar = os.path.join(pdf_dir, "downloaded.json")
        if os.path.exists(sidecar):
            with open(sidecar) as f:
                dl = json.load(f)
            print(f"[status]   downloaded.json: {len(dl)} entries (DOI dedup active)")
    else:
        print(f"[status] pdfs/: not found (no PDFs downloaded)")

    # Check for web/ and supplement/ subdirs
    subdir_has_papers = False
    for sub in ["web", "supplement"]:
        sub_dir = os.path.join(d, sub)
        if os.path.isdir(sub_dir):
            jf = os.path.join(sub_dir, "papers.json")
            if os.path.exists(jf):
                with open(jf) as f:
                    sp = json.load(f)
                subdir_has_papers = True
                print(f"[status] {sub}/: {len(sp)} papers")
            else:
                print(f"[status] {sub}/: directory exists, papers.json not found")
        elif sub == "supplement":
            pass  # optional
        else:
            print(f"[status] {sub}/: not found")

    if not papers and not subdir_has_papers and not os.path.isdir(pdf_dir):
        print(f"[status] → Empty project. Ready for fresh search.")


def search(cdp: CDPClient, query: str, journals: list[str], years: str,
            max_count: int = 500, output_dir: str = ".", merge_with_existing: bool = False,
            full_text_only: bool = False, peer_reviewed_only: bool = False,
            profile: str = "bsc", database_scope: str = "econ",
            source_type_scope: str = "academic", use_so_query: bool = False,
            use_journal_filter: bool = True):
    """Run EBSCO search and save results."""
    print(f"[search] Query: {query}")
    print(f"[search] Journals: {journals}")
    print(f"[search] Date range: {years}")
    print(f"[search] Profile: {profile}")
    print(f"[search] Database scope: {database_scope}")
    print(f"[search] Source type scope: {source_type_scope}")
    print(f"[search] Journal facet filter: {'on' if use_journal_filter else 'off'}")
    print(f"[search] SO query filter: {'on' if use_so_query else 'off'}")

    # Warn if SO terms are in query but --journals not used
    if not journals:
        import re as _re2
        so_hits = _re2.findall(r'SO\s+"([^"]+)"', query)
        if so_hits:
            print(f"[search] ⚠  SO terms in query but --journals not set. Journal filter is OFF.")
            print(f"[search] ⚠  EBSCO SO does substring matching — non-target journals WILL leak through.")
            print(f"[search] ⚠  Add: --journals \"{', '.join(so_hits[:5])}\"")

    if full_text_only:
        print(f"[search] Limiter: FT y (full text only)")
    if peer_reviewed_only:
        print(f"[search] Limiter: RV y (peer reviewed only)")

    js = build_search_js(query, journals, years, max_count, full_text_only, peer_reviewed_only,
                         profile, database_scope, source_type_scope, use_so_query,
                         use_journal_filter)
    print(f"[search] Running search (max {max_count} papers)...")

    result = cdp.eval(js, await_promise=True, timeout_ms=300_000)
    papers = result.get("papers", [])
    raw_count = len(papers)

    # Print facets summary (journal distribution, subjects, etc.)
    facets = result.get("facets")
    if facets:
        print(f"[search] Facets from EBSCO (db total: {result.get('db_total', '?')}):")
        for facet in facets:
            if not facet.get("values"):
                continue
            label = facet.get("label", facet.get("id", "?"))
            top = facet["values"][:10]
            summary = ", ".join(f'{v["value"]}({v["count"]})' for v in top)
            print(f"[search]   {label}: {summary}")

    # Filter to journal matches (EBSCO SO field does substring matching).
    # Venue names from EBSCO are messy — publisher prefixes, "The" variants,
    # citation-text leakage, etc. We normalize aggressively before matching.
    if journals:
        import re as _re

        # Publisher / database prefixes that may appear in venue strings
        _PUBLISHER_PREFIXES = [
            r'^oxford university press(?: \(oup\))?,\s*',
            r'^president and fellows of harvard college,\s*',
            r'^university of chicago press,\s*',
            r'^american economic association,\s*',
            r'^wiley-blackwell,\s*',
            r'^wiley,\s*',
            r'^taylor\s*&amp;\s*francis(?: journals)?,\s*',
            r'^elsevier(?: b\.?v\.?)?,\s*',
            r'^centro de economia politica,\s*',
            r'^institute of economic research,\s*',
            r'^instytut badan gospodarczych,\s*',
        ]
        # Extra text that sometimes leaks into the venue string
        _TAIL_JUNK = [
            r'\s*;\s*volume\b.*$',
            r'\s*;\s*issn\b.*$',
            r'\s*;\s*vol\.\s*\d+.*$',
            r'\s*vol\.\s*\d+.*$',
        ]

        def _norm(v: str) -> str:
            v = v.strip()
            # Decode HTML entities
            v = v.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            # Strip publisher prefixes
            for pat in _PUBLISHER_PREFIXES:
                v = _re.sub(pat, '', v, flags=_re.IGNORECASE)
            # Strip trailing citation junk
            for pat in _TAIL_JUNK:
                v = _re.sub(pat, '', v, flags=_re.IGNORECASE)
            v = v.strip()
            # Remove "The " prefix (case-insensitive)
            v = _re.sub(r'^the\s+', '', v, flags=_re.IGNORECASE)
            # Normalize: lowercase, drop periods, collapse whitespace
            v = v.lower().replace('.', '').replace('  ', ' ').strip()
            return v

        journal_norms = {_norm(j) for j in journals}
        filtered = []
        rejected = []
        for p in papers:
            vn = _norm(p.get("venue", ""))
            # Try exact match first, then contains match
            matched = vn in journal_norms
            if not matched:
                # Check if the normalized venue CONTAINS any normalized journal name
                # (handles residual prefixes / suffixes the publisher list didn't cover)
                for jn in journal_norms:
                    if jn in vn or vn in jn:
                        # Extra guard: reject false-positives where journal name is
                        # embedded in a longer name (e.g. "brazilian journal of political economy"
                        # contains "journal of political economy" but is NOT JPE)
                        if jn == 'journal of political economy' and ('macro' in vn or 'brazilian' in vn or 'scottish' in vn or 'european' in vn or 'international' in vn or 'equilibrium' in vn):
                            continue
                        if jn == 'american economic review' and 'insights' in vn:
                            continue
                        if jn == 'quarterly journal of economics' and ('equilibrium' in vn or 'management' in vn):
                            continue
                        if jn == 'econometrica' and 'econometric' in vn and vn != 'econometrica':
                            continue
                        matched = True
                        break
            if matched:
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

    # Merge with existing results if --merge flag
    merged_with_existing = 0
    json_path = os.path.join(output_dir, "papers.json")
    if merge_with_existing and os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            existing = json.load(f)
        # Build dedup index by DOI (preferred) or ebsco_id
        seen_doi = set()
        seen_eid = set()
        for p in existing:
            doi = (p.get("doi") or "").strip().lower()
            eid = (p.get("ebsco_id") or "").strip()
            if doi:
                seen_doi.add(doi)
            if eid:
                seen_eid.add(eid)
        new_papers = []
        for p in papers:
            doi = (p.get("doi") or "").strip().lower()
            eid = (p.get("ebsco_id") or "").strip()
            if (doi and doi in seen_doi) or (eid and eid in seen_eid):
                merged_with_existing += 1
                continue
            new_papers.append(p)
            if doi:
                seen_doi.add(doi)
            if eid:
                seen_eid.add(eid)
        papers = existing + new_papers
        print(f"[search] Merged: {len(new_papers)} new + {len(existing)} existing = {len(papers)} total ({merged_with_existing} duplicates skipped)")
    else:
        print(f"[search] {len(papers)} papers (merge off — overwriting output)")

    # Re-index
    for i, p in enumerate(papers, 1):
        p["idx"] = i

    # Save JSON
    os.makedirs(output_dir, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    print(f"[search] Saved to {json_path}")

    # Generate manifest.csv
    manifest_path = os.path.join(output_dir, "manifest.csv")
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "year", "first_author", "title", "venue", "doi", "has_pdf", "doc_types", "subjects", "source"])
        for i, p in enumerate(papers, 1):
            doc_types = ";".join(p.get("doc_types", []))
            subjects = ";".join(p.get("subjects", [])[:5])  # first 5 subjects
            w.writerow([f"{i:03d}", p["year"], p["first_author"], p["title"], p["venue"],
                        p.get("doi", ""), p["has_pdf"], doc_types, subjects, "ebsco"])
    print(f"[search] Manifest: {manifest_path}")

    return papers


# ── Resolve: web-found papers → EBSCO records (attach pdf_url) ───

def _norm_title(t: str) -> str:
    """Normalize a title for fuzzy matching: lowercase, strip punctuation,
    drop leading articles, collapse whitespace."""
    import re as _re
    import html as _html
    t = _html.unescape(t or "")
    t = t.lower()
    t = _re.sub(r"[\.,:;!?()\[\]{}\"'“”‘’«»—–\-]", " ", t)
    t = _re.sub(r"^(a|an|the)\s+", "", t)
    t = _re.sub(r"\s+", " ", t).strip()
    return t


def _title_sim(a: str, b: str) -> float:
    """Levenshtein ratio between two normalized titles. Pure stdlib."""
    a = _norm_title(a)
    b = _norm_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Levenshtein edit distance (iterative, O(len(a)*len(b)))
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


def _build_resolve_js(doi: str, title: str) -> str:
    """Build JS that queries EBSCO for ONE paper: DOI lookup first, then
    title search. Returns up to 5 candidate records (id, doi, title, source,
    has_pdf, pdf_url) for Python-side matching."""
    # Prefer DOI-anchored query; fall back to title phrase.
    if doi:
        q = f'DI "{doi}"'
    else:
        # Strip quotes from title to keep query well-formed
        safe = (title or "").replace('"', "")
        q = f'TI "{safe}"'
    js_template = '''async () => {
    const BASE = 'https://research-ebsco-com-443.webvpn.cufe.edu.cn';
    const API = BASE + '/api/search/v1/search?applyAllLimiters=true';
    const QUERY = __QUERY__;
    const resp = await fetch(API, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            query: QUERY, profileIdentifier: 'k3svp7', searchMode: 'all',
            sort: 'relevance', offset: 0, count: 5, userDirectAction: true,
            expanders: ['fullText', 'concept']
        })
    });
    const data = await resp.json();
    const items = data?.search?.items || [];
    return items.map(item => {
        const title = typeof item.title === 'string' ? item.title : (item.title?.value || '');
        const hasPDF = item.links?.downloadLinks?.some(l => l.type === 'pdf') || false;
        const pdfUrl = hasPDF
            ? BASE + '/api/search/v1/record/' + item.id + '/fulltext/pdf?sourceRecordId=' + item.id + '&opid=k3svp7&intent=download'
            : null;
        return {
            ebsco_id: item.id, doi: item.doi || null, title: title,
            venue: item.source || '', has_pdf: hasPDF, pdf_url: pdfUrl,
            year: parseInt((item.publicationDate || item.coverDate || '').slice(0,4)) || null
        };
    });
}'''
    return js_template.replace('__QUERY__', json.dumps(q))


def resolve(cdp: CDPClient, manifest_path: str, output_path: str = None,
            title_threshold: float = 0.85):
    """Enrich a web-discovered papers.json with EBSCO record IDs + pdf_url.

    For each paper: query EBSCO by DOI (exact), else by title (fuzzy match
    ≥ title_threshold). On match, attach ebsco_id, pdf_url, has_pdf. Papers
    with no EBSCO match keep their oa_url (web OA fallback) and get
    ebsco_unmatched=true.

    Writes enriched papers.json (in place unless output_path given) so the
    download command can consume it.
    """
    json_path = manifest_path
    if not os.path.exists(json_path):
        alt = os.path.join(os.path.dirname(json_path), "papers.json")
        if os.path.exists(alt):
            json_path = alt
    with open(json_path, encoding="utf-8") as f:
        papers = json.load(f)

    print(f"[resolve] {len(papers)} web-discovered papers to resolve against EBSCO")

    matched = 0
    matched_pdf = 0
    unmatched = 0
    for i, p in enumerate(papers, 1):
        # Skip if already resolved (has EBSCO pdf_url from a prior run)
        if p.get("pdf_url") and p.get("ebsco_id"):
            matched += 1
            matched_pdf += 1
            continue

        doi = (p.get("doi") or "").strip()
        title = p.get("title") or ""
        cand = []

        # Pass 1: DOI lookup
        if doi:
            try:
                cand = cdp.eval(_build_resolve_js(doi, ""), await_promise=True, timeout_ms=30000) or []
            except Exception as e:
                print(f"[resolve]   {i}/{len(papers)}: DOI query error: {e}")
                cand = []

        hit = None
        # DOI candidates: accept first whose title clears a loose cross-check (0.70),
        # guarding against a bad DOI resolving to an unrelated record.
        for c in cand:
            if c.get("doi") and doi and c["doi"].strip().lower() == doi.lower():
                if not title or _title_sim(title, c.get("title", "")) >= 0.70:
                    hit = c
                    break
        # Pass 2: title search fallback
        if not hit and title:
            try:
                tcand = cdp.eval(_build_resolve_js("", title), await_promise=True, timeout_ms=30000) or []
            except Exception as e:
                print(f"[resolve]   {i}/{len(papers)}: title query error: {e}")
                tcand = []
            best = None
            best_sim = 0.0
            for c in tcand:
                sim = _title_sim(title, c.get("title", ""))
                if sim > best_sim:
                    best_sim = sim
                    best = c
            if best and best_sim >= title_threshold:
                hit = best

        if hit:
            p["ebsco_id"] = hit["ebsco_id"]
            p["has_pdf"] = hit.get("has_pdf", False)
            p["pdf_url"] = hit.get("pdf_url")
            if not p.get("doi") and hit.get("doi"):
                p["doi"] = hit["doi"]
            if not p.get("venue") and hit.get("venue"):
                p["venue"] = hit["venue"]
            p["ebsco_unmatched"] = False
            matched += 1
            if p.get("pdf_url"):
                matched_pdf += 1
            tag = "PDF" if p.get("pdf_url") else "no-pdf"
            print(f"[resolve]   {i}/{len(papers)}: MATCH {hit['ebsco_id']} ({tag}) — {title[:50]}")
        else:
            p["ebsco_unmatched"] = True
            # Keep oa_url as fallback download source (handled by download cmd)
            unmatched += 1
            oa = "oa" if p.get("oa_url") else "none"
            print(f"[resolve]   {i}/{len(papers)}: NO EBSCO MATCH (fallback={oa}) — {title[:50]}")
        time.sleep(0.3)  # polite pacing

    # Re-index
    for i, p in enumerate(papers, 1):
        p["idx"] = i

    out = output_path or json_path
    with open(out, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)
    print(f"[resolve] {matched} matched EBSCO ({matched_pdf} with PDF), {unmatched} unmatched")
    print(f"[resolve] Saved enriched papers.json → {out}")

    # Regenerate manifest.csv alongside
    manifest_csv = os.path.join(os.path.dirname(out), "manifest.csv")
    with open(manifest_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "year", "first_author", "title", "venue", "doi", "has_pdf", "ebsco_id", "ebsco_unmatched", "oa_url", "source"])
        for i, p in enumerate(papers, 1):
            w.writerow([f"{i:03d}", p.get("year", ""), p.get("first_author", ""),
                        p.get("title", ""), p.get("venue", ""), p.get("doi", ""),
                        p.get("has_pdf", False), p.get("ebsco_id", ""),
                        p.get("ebsco_unmatched", ""), p.get("oa_url", ""),
                        ";".join(p.get("sources", [])) if isinstance(p.get("sources"), list) else p.get("source", "")])
    print(f"[resolve] Manifest: {manifest_csv}")
    return papers


# ── PDF Download ────────────────────────────────────────────────

def _recover_session(cdp: CDPClient) -> bool:
    """Full session recovery: restart Chrome + re-auth VPN/EBSCO.

    Call this when chunk evals start failing — cookie injection alone
    won't fix an expired VPN session. Returns True if recovery succeeded.
    """
    print("[download] Session recovery: restarting Chrome + re-auth...")
    cdp.close()
    import subprocess as _sp

    # Kill all Chrome processes on debug port
    try:
        result = _sp.run(["lsof", "-ti", "tcp:9222"], capture_output=True, text=True)
        for pid_str in result.stdout.strip().split("\n"):
            if pid_str:
                try:
                    os.kill(int(pid_str), 9)
                except OSError:
                    pass
    except Exception:
        pass
    time.sleep(3)

    # Restart Chrome
    ensure_chrome()
    time.sleep(2)

    # Reconnect CDP
    try:
        cdp.connect()
    except Exception as e:
        print(f"[download] Reconnect failed: {e}")
        return False

    # Re-establish EBSCO session (full SSO, not just cookie injection)
    if not setup_session(cdp):
        print("[download] Session recovery: setup_session failed")
        return False

    print("[download] Session recovery: OK")
    return True

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
    const FETCH_TIMEOUT = 30000;  // per-PDF fetch timeout (ms) — prevents stalled chunks
    const results = [];
    for (let i = 0; i < items.length; i += CONCURRENCY) {
        const sub = items.slice(i, i + CONCURRENCY);
        const fetched = await Promise.all(sub.map(async (item) => {
            try {
                const ctrl = new AbortController();
                const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
                const resp = await fetch(item.url, {signal: ctrl.signal});
                clearTimeout(timer);
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
                const msg = e.name === 'AbortError' ? 'fetch timeout (' + (FETCH_TIMEOUT/1000) + 's)' : (e.message || String(e));
                return Object.assign({}, item, {error: msg});
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

        # Download URL priority: EBSCO pdf_url (institutional, primary) →
        # oa_url (open-access web fallback, set by resolve for unmatched papers).
        pdf_papers = []
        for p in papers:
            url = p.get("pdf_url") or p.get("oa_url")
            if url:
                p["_dl_url"] = url
                pdf_papers.append(p)
        total = len(pdf_papers)
        ebsco_n = sum(1 for p in pdf_papers if p.get("pdf_url"))
        oa_n = total - ebsco_n
        print(f"[download] {total}/{len(papers)} papers downloadable ({ebsco_n} via EBSCO, {oa_n} via OA fallback)")

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

        # Session stability warning for large downloads
        if len(pending) > 100:
            print(f"[download] ⚠  {len(pending)} PDFs pending — CDP session may degrade.")
            print(f"[download] ⚠  If download stalls, kill & re-run. downloaded.json dedup ensures forward progress.")
            print(f"[download] ⚠  Expect 2–4 runs for reliable completion.")

        # Build chunk items for all pending papers
        pending_dois = {}  # idx → doi for sidecar recording
        all_items = []
        for i, p in enumerate(pending):
            name = _paper_filename(p)
            doi = (p.get("doi") or "").strip().lower()
            all_items.append({"url": p.get("_dl_url") or p["pdf_url"], "name": name, "idx": i + 1, "doi": doi})
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
                print("[download] CDP connection lost. Attempting full session recovery...")
                if not _recover_session(cdp):
                    print("[download] Session recovery failed. Queueing chunk for retry.")
                    for item in chunk:
                        retry_queue.append({**item, "_last_error": "CDP dead, recovery failed"})
                    continue
                print("[download] Session recovered, resuming chunk.")

            js = _download_chunk_js(chunk)
            try:
                results = cdp.eval(js, await_promise=True, timeout_ms=chunk_timeout_ms)
            except Exception as e:
                print(f"[download] Chunk {ci+1} eval failed: {e}")
                # Session may be dead — attempt full recovery before retrying
                if _recover_session(cdp):
                    # Retry the failed chunk immediately with fresh session
                    print(f"[download] Re-running chunk {ci+1} after recovery...")
                    try:
                        results = cdp.eval(js, await_promise=True, timeout_ms=chunk_timeout_ms)
                    except Exception as e2:
                        print(f"[download] Chunk {ci+1} still failed after recovery: {e2}")
                        for item in chunk:
                            retry_queue.append({**item, "_last_error": str(e2)})
                        continue
                else:
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
    sp.add_argument("--merge", action="store_true", help="Merge with existing papers.json instead of overwriting")
    sp.add_argument("--full-text", action="store_true", help="Only return papers with full text available (FT y)")
    sp.add_argument("--peer-reviewed", action="store_true", help="Only return peer-reviewed papers (RV y)")
    sp.add_argument("--profile", default="bsc", choices=sorted(EBSCO_PROFILES),
                    help="EBSCO profile: bsc (default, cleaner), general, or all (broad/noisy)")
    sp.add_argument("--database-scope", default="econ", choices=sorted(DATABASE_FILTERS),
                    help="API database facet filter: econ (default: eoh,bth,edb), bsc, econlit, none")
    sp.add_argument("--source-type", default="academic", choices=sorted(SOURCE_TYPE_FILTERS),
                    help="API source type facet filter: academic (default) or none")
    sp.add_argument("--use-so-query", action="store_true",
                    help="Also add SO \"Journal\" clauses to query. Default uses Journal facet filter only.")
    sp.add_argument("--no-journal-filter", action="store_true",
                    help="Disable API Journal facet filter; post-search Python journal filter still runs if --journals is set.")

    # status subcommand
    stp = sub.add_parser("status", help="Check existing content in a project directory")
    stp.add_argument("directory", nargs="?", default="./refs", help="Project directory to check (e.g., refs/patents-top5)")

    # resolve subcommand — enrich web-discovered papers with EBSCO pdf_url
    rp = sub.add_parser("resolve", help="Resolve web-discovered papers.json against EBSCO (attach ebsco_id + pdf_url)")
    rp.add_argument("--manifest", required=True, help="Path to web-discovered papers.json")
    rp.add_argument("--output", "-o", default=None, help="Output path (default: in-place)")
    rp.add_argument("--title-threshold", type=float, default=0.85, help="Min Levenshtein title similarity for fuzzy match (default 0.85)")

    # download subcommand
    dp = sub.add_parser("download")
    dp.add_argument("--manifest", required=True, help="Path to papers.json or manifest.csv")
    dp.add_argument("--output", "-o", default=None, help="Output directory for PDFs (default: <manifest_dir>/pdfs/)")
    dp.add_argument("--chunk-size", type=int, default=15, help="PDFs per chunk (default 15)")
    dp.add_argument("--retry", type=int, default=2, help="Retry count for transient failures (default 2)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "status":
        cmd_status(args.directory)
        return

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
            search(cdp, args.query, journals, args.years, args.max, args.output, args.merge,
                   args.full_text, args.peer_reviewed, args.profile, args.database_scope,
                   args.source_type, args.use_so_query, not args.no_journal_filter)

        elif args.command == "resolve":
            setup_session(cdp)
            resolve(cdp, args.manifest, args.output, args.title_threshold)

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
