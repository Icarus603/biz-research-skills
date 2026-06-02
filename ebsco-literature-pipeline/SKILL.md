---
name: ebsco-literature-pipeline
description: Literature discovery and bulk PDF download via EBSCO Search API. Auto-starts Chrome, auto-login CUFE VPN, parallel PDF download. CRITICAL: ANY request to find, search, collect, or download academic papers IS a request to get PDFs on local disk. No "search-only" mode. Output is always PDF files + manifest.csv. Triggers on: 找论文 搜文献 下论文 文献检索 搜论文 下载论文 找文献 论文搜索 文献收集 查文献 学术搜索 期刊论文 英文文献 find papers search literature download papers get papers collect literature literature search academic papers bulk download journal articles.
---

# EBSCO Literature Pipeline

Systematic literature discovery + bulk PDF download via CUFE WebVPN + EBSCO.

```
Topic
  -> Phase 0: TOPIC ANALYSIS (classify -> domain mapping)
  -> Phase 1: SEARCH (EBSCO API via CDP, parallel keyword + domain queries)
  -> Phase 2: DOWNLOAD (parallel fetch+blob, named PDFs)
  -> Phase 3: MANIFEST (manifest.csv + papers.json)
```

## Prerequisites

- Chrome running with `--remote-debugging-port=9222`
- CUFE WebVPN credentials in `~/.cufe_credentials` (one-time setup)
- EBSCO session cookies auto-persisted at `~/.cache/ebsco-pipeline/session_cookies.json`

### One-time setup

```bash
# One-time: create credentials file
cat > ~/.cufe_credentials << EOF
CUFE_USERNAME=你的学号
CUFE_PASSWORD=你的密码
EOF
chmod 600 ~/.cufe_credentials
```

Chrome is auto-started by the pipeline on first run. No manual setup needed.

---

## Phase 0: Topic Analysis

**CRITICAL — keyword search fails for empirical-measure topics.** Before searching, classify the topic:

| Type | Definition | Example | Strategy |
|------|-----------|---------|----------|
| **A: Direct topic** | Paper titles contain the topic word | "minimum wage", "carbon tax", "Brexit" | Keyword search suffices |
| **B: Empirical measure** | Papers use this as DATA but titles describe the RESEARCH DOMAIN | "patents" -> "innovation", "credit scores" -> "consumer credit", "scanner data" -> "consumer behavior" | **Domain search** required |
| **C: Broad theme** | Papers study this but don't name it explicitly | "inequality", "economic development" | Hybrid: domain + keyword |

**Rule for Type B/C**: Search the RESEARCH DOMAIN, not the topic word. E.g., for "patents", search `innovation OR R&D OR "technological change" OR inventor`, not `patent` alone. See `references/ebsco_search_api.md` for domain-term mappings.

### Journal scope

If user specifies a journal list, use EBSCO's `SO "Journal Name"` field code:

```
(SO "American Economic Review" OR SO "Quarterly Journal of Economics") AND (domain terms) AND DT 2022-2026
```

Supported journal lists in `references/journal_lists.md`.

---

## Phase 1: Search

### CLI

```bash
python3 scripts/ebsco_pipeline.py search "innovation OR patent OR R&D" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 \
  --max 500 \
  --output ./papers/
```

### What it does

1. **Session setup** (auto):
   - Try cookie injection from `~/.cache/ebsco-pipeline/session_cookies.json`
   - If cookies valid -> skip SSO, go to search
   - If cookies expired/missing -> read `~/.cufe_credentials` -> auto-fill CAS login form -> SSO login -> save cookies

2. **Search** (EBSCO API via CDP `Runtime.evaluate`):
   - POST to `https://research-ebsco-com-443.webvpn.cufe.edu.cn/api/search/v1/search?applyAllLimiters=true`
   - EBSCO query syntax with `SO`, `AND`, `OR`, `DT` field codes
   - Pagination: 50 per page, auto-page until `max` papers or exhausted
   - Each paper: title, author, year, venue, DOI, abstract, has_pdf flag, pdf_url

3. **Output**:
   - `papers.json` — full metadata with `idx`, `pdf_url`, `has_pdf`
   - `manifest.csv` — idx, year, author, title, venue, doi, has_pdf, source

### EBSCO query syntax

| Code | Field | Example |
|------|-------|---------|
| `TI` | Title | `TI "Patent Publication"` |
| `SO` | Source/Journal | `SO "American Economic Review"` |
| `DT` | Date range | `DT 2022-2026` |
| `AB` | Abstract | `AB patent` |
| `SU` | Subject | `SU innovation` |
| `AU` | Author | `AU Acemoglu` |
| `FT` | Full text available | `FT y` |

Full API reference: `references/ebsco_search_api.md`

---

## Phase 2: Download

### CLI

```bash
python3 scripts/ebsco_pipeline.py download \
  --manifest ./papers/papers.json \
  --output ./papers/ \
  --chunk-size 30
```

### What it does

1. Reads `papers.json`, finds papers with `has_pdf: true` and valid `pdf_url`
2. Skips already-downloaded papers (checks output dir)
3. **Chunked parallel download** (default 30 PDFs per chunk):
   - Each chunk: 10 concurrent fetches per sub-batch, then `<a download>` click
   - Chunks run sequentially; within each chunk PDFs download in parallel
   - 500ms pause between sub-batches so Chrome can flush downloads
   - Each chunk has its own CDP eval timeout (scales with chunk size)
4. **Post-chunk move**: After each chunk, files are moved from `~/Downloads/` to `--output` (Chrome ignores `downloadPath` for blob URLs, so `~/Downloads` is always used first)
5. **Final sweep**: After all chunks, any remaining files in `~/Downloads` are moved
6. **Naming**: `{FirstAuthor}_{Year}_{Title_60chars}.pdf`
7. Skips papers where EBSCO returns 400/403 (no institutional access)

### `--chunk-size`

Controls PDFs per CDP eval call. Default 30. Lower to 15-20 if timeouts persist. Each chunk gets `max(120s, chunk_size * 5s)` timeout.

### Supported formats

- PDF (application/pdf) — downloaded
- EBSCO record with `has_pdf: false` — skipped

---

## Phase 3: Manifest

Generated automatically by the search command:

**manifest.csv**:
```
idx,year,first_author,title,venue,doi,has_pdf,source
001,2023,Hegde,Patent Publication and Innovation,Journal of Political Economy,10.1086/723636,True,ebsco
...
```

**papers.json** includes full metadata + `ebsco_id` and `pdf_url` for each paper.

---

## Architecture

### CDP Client (`scripts/cdp_client.py`)

Pure Python stdlib WebSocket client for Chrome DevTools Protocol. Zero dependencies.

- Connects to `ws://127.0.0.1:9222`
- Supports `Page.navigate`, `Runtime.evaluate` (sync + async), `Network.getCookies/setCookie`, `Browser.setDownloadBehavior`
- Auto-wraps `async () => { }` in IIFE for `awaitPromise`

### Pipeline (`scripts/ebsco_pipeline.py`)

CLI with `search` and `download` subcommands.

**Session auto-management**:
- Cookie injection (fast path, no SSO)
- Auto SSO login fallback (reads `~/.cufe_credentials`)
- Cookie persistence after successful login

### EBSCO API (`references/ebsco_search_api.md`)

Complete API reference for EBSCO Search API accessed via CUFE WebVPN proxy.

---

## Anti-Patterns

| Approach | Why It Fails |
|----------|-------------|
| Keyword search for empirical-measure topics | Papers use "innovation" not "patent" in titles |
| `curl` standalone EBSCO API calls | VPN requires SSO-bound TLS session |
| Title-only queries on EBSCO | Low recall vs. domain search with SO+DT filters |
| `window.open` for PDF download | Popup blocker + no filename control |
| iframe-based PDF download | Downloads HTML pages, not PDF content |
| Downloading 500+ PDFs in one chunk | Timeout. Use `--chunk-size 30` (default) |
| `Browser.setDownloadBehavior` with blob URLs | Doesn't affect blob URL saves |

---

## Files

| File | Purpose |
|------|---------|
| `scripts/cdp_client.py` | Pure stdlib CDP WebSocket client |
| `scripts/ebsco_pipeline.py` | CLI: search + download |
| `references/ebsco_search_api.md` | EBSCO API reference |
| `references/journal_lists.md` | Journal scope definitions |
| `references/openalex_api_protocol.md` | OpenAlex API patterns (supplementary) |
| `references/crossref_api_protocol.md` | Crossref API patterns (supplementary) |
| `references/semantic_scholar_api_protocol.md` | S2 API patterns (supplementary) |
| `agents/bibliography_agent.md` | Aggregation agent (supplementary) |

---

## Quick Start

```bash
# 1. One-time: credentials only
echo 'CUFE_USERNAME=学号' > ~/.cufe_credentials
echo 'CUFE_PASSWORD=密码' >> ~/.cufe_credentials
chmod 600 ~/.cufe_credentials

# 2. Just run — Chrome auto-starts, auto-logs in
python3 scripts/ebsco_pipeline.py search "innovation OR patent OR R&D OR \"intellectual property\" OR inventor" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 --max 500 --output ./papers/

# 3. Download PDFs (chunked parallel, 30 per chunk)
python3 scripts/ebsco_pipeline.py download --manifest ./papers/papers.json --chunk-size 30

# 4. Results
ls ~/Downloads/*.pdf       # or --output dir after auto-move
cat papers/manifest.csv    # Paper metadata
```
python3 scripts/ebsco_pipeline.py search "innovation OR patent OR R&D OR \"intellectual property\" OR inventor" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 --max 500 --output ./papers/

# 3. Download PDFs (chunked parallel, 30 per chunk)
python3 scripts/ebsco_pipeline.py download --manifest ./papers/papers.json --chunk-size 30

# 4. Results
ls ~/Downloads/*.pdf       # Named PDFs
cat papers/manifest.csv    # Paper metadata
