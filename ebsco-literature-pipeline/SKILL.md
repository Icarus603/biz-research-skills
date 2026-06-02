---
name: ebsco-literature-pipeline
description: Literature discovery and bulk PDF download via EBSCO Search API. Auto-starts Chrome, auto-login CUFE VPN, parallel PDF download. CRITICAL: ANY request to find, search, collect, or download academic papers IS a request to get PDFs on local disk. No "search-only" mode. Output is always PDF files + manifest.csv. Triggers on: 找论文 搜文献 下论文 文献检索 搜论文 下载论文 找文献 论文搜索 文献收集 查文献 学术搜索 期刊论文 英文文献 find papers search literature download papers get papers collect literature literature search academic papers bulk download journal articles.
---

# EBSCO Literature Pipeline

Systematic literature discovery + bulk PDF download via CUFE WebVPN + EBSCO.

```
Topic
  -> Phase 0: STATUS CHECK (check existing refs/ content — NEVER skip this)
  -> Phase 1: TOPIC ANALYSIS (classify -> domain mapping -> decompose into subtopic waves)
  -> Phase 2: SEARCH LOOP (fire wave after wave, --merge, until exhaustion gate met — NEVER one-and-done)
  -> Phase 3: DOWNLOAD (parallel fetch+base64 decode, DOI dedup, retry on transient errors)
  -> Phase 4: MANIFEST (manifest.csv + papers.json + downloaded.json sidecar)
  -> Loop back to Phase 2 if download surfaced new angles or user says "more"
```

## Prime Directive: EXHAUST, don't sample

A literature request is a request to find **everything** that matches, not a sample.
ONE search wave is NEVER enough for a broad/exhaustive ask ("所有 / 全部 / 多多益善 /
all / as many as possible / comprehensive"). You MUST keep firing search waves across
distinct sub-angles until the **exhaustion gate** (Phase 2) is provably met, THEN download,
THEN report. Stopping after one wave and asking the user "want more?" is a FAILURE mode —
the user already said more. Do the waves yourself.

## Output Convention (MANDATORY)

**Every invocation MUST follow this layout. No exceptions. No ad-hoc paths.**

```
refs/
  {project-slug}/              # kebab-case, e.g. "patents-top5", "ai-labor-market"
    papers.json                # merged metadata (all searches deduplicated)
    manifest.csv               # merged manifest for human review
    search/                    # raw primary search results
      papers.json
      manifest.csv
    supplement/                # supplementary searches (if any)
      {query-slug}/
        papers.json
        manifest.csv
    pdfs/                      # downloaded PDFs (download command auto-creates this)
      downloaded.json          # DOI → filename sidecar
      Author_Year_Title.pdf
```

**Rules for agents:**
1. **ALWAYS run `status` FIRST** — before any search. Check what already exists.
2. `--output` for `search` always points to `refs/{project-slug}/search/`
3. `--output` for `download` is OMITTED — it auto-derives `pdfs/` from the manifest directory
4. After all searches complete, merge + deduplicate into `refs/{project-slug}/papers.json` and `manifest.csv`
5. Project slug: kebab-case, short, descriptive. Derived from user's request topic.
6. Never write directly into `refs/` root — always into a project subdirectory.
7. Use `--merge` flag on subsequent searches to avoid overwriting previous results.

## Prerequisites

- CUFE WebVPN credentials in `~/.cufe_credentials` (one-time setup)
- EBSCO session cookies auto-persisted at `~/.cache/ebsco-pipeline/session_cookies.json`

### Chrome: fully automatic — DO NOT TOUCH

`ensure_chrome()` in `ebsco_pipeline.py` handles everything:

| Detail | Value |
|--------|-------|
| Mode | `--headless=new` (invisible, no GUI window) |
| Profile | `~/.cache/ebsco-pipeline/chrome-profile` (isolated from user's normal Chrome) |
| Port check | Only kills processes on port 9222, never touches user's Chrome |
| Startup | Automatic on first `search` or `download` command |

**CRITICAL for agents: NEVER manually start Chrome, kill Chrome, or run `killall "Google Chrome"`. The pipeline manages its own headless Chrome instance with a dedicated profile. It does not conflict with the user's normal Chrome in any way. Manual intervention is the ONLY thing that can break the user's existing session.**

### One-time setup

```bash
# One-time: create credentials file
cat > ~/.cufe_credentials << EOF
CUFE_USERNAME=你的学号
CUFE_PASSWORD=你的密码
EOF
chmod 600 ~/.cufe_credentials
```

---

## Phase 0: Status Check (ALWAYS FIRST)

Before any search, check what already exists:

```bash
python3 scripts/ebsco_pipeline.py status refs/{project-slug}/
```

Reports: paper count, year range, venue distribution, PDF count/disk size, sidecar state. No Chrome needed.

---

## Phase 1: Topic Analysis (build query)

**CRITICAL — keyword search fails for empirical-measure topics.** Before searching, classify the topic:

| Type | Definition | Example | Strategy |
|------|-----------|---------|----------|
| **A: Direct topic** | Paper titles contain the topic word | "minimum wage", "carbon tax", "Brexit" | Keyword search suffices |
| **B: Empirical measure** | Papers use this as DATA but some titles describe the RESEARCH DOMAIN | "patents" → some papers titled "innovation"; "credit scores" → some papers titled "consumer credit" | **Anchor on controlled vocab + TI/AB, add domain terms for recall** |
| **C: Broad theme** | Papers study this but don't name it explicitly | "inequality", "economic development" | Hybrid: domain + keyword |

**Rule for ALL types — NEVER drop the topic word.** Use EBSCO's `DE` (controlled vocabulary descriptor) as the precision anchor. `TI` and `AB` expand recall. Domain terms are ADDITIVE only.

**Correct query construction for Type B:**
```
(DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent OR TI "intellectual property")
```
Then combine with journal filter and date range. Do NOT replace the topic with domain terms.

**Why domain-only fails**: `innovation OR R&D OR "technological change"` in Top-5 econ journals returns hundreds of papers about firm dynamics, technology adoption, management — most with zero connection to patents. Precision collapses to 30-40%.

**When to add domain terms**: Only for recall boost on top of the anchor. Use `OR` to append, never to replace:
```
(DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent) OR (TI inventor AND AB "R&D")
```

See `references/ebsco_search_api.md` for `DE` descriptor values and domain-term patterns.

### Journal scope

If user specifies a journal list, use EBSCO's `SO "Journal Name"` field code:

```
(SO "American Economic Review" OR SO "Quarterly Journal of Economics") AND (domain terms) AND DT 2022-2026
```

Supported journal lists in `references/journal_lists.md`.

### Decompose into subtopic waves (MANDATORY for broad asks)

A broad topic = a UNION of narrower angles. One query can't capture all of them with both
precision and recall. Before searching, write down a **wave plan**: 4-8 distinct queries,
each anchored on the topic but targeting a different sub-angle the user named or implied.

Example — user asks for "all patent-related empirical papers in Top-5, 2022-2026":

| Wave | Angle | Query anchor (combine with --journals + --years + --merge) |
|------|-------|------------------------------------------------------------|
| 1 | Core patents | `DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent OR TI inventor` |
| 2 | Innovation/R&D domain | `DE "Technological innovations" OR DE "Patent applications" OR AB "patent citations" OR AB "patent data"` |
| 3 | Litigation/transfer/licensing | `DE "Patent infringement" OR DE "Patent licenses" OR AB "patent litigation" OR AB "patent transfer" OR AB licensing` |
| 4 | Spillovers/citations/text | `AB "knowledge spillover" OR AB "technology spillover" OR AB "patent citations" OR AB "patent text"` |
| 5 | Trade/IP/tech-transfer | `DE "Technology transfer" OR DE "Trade secrets" OR AB "intellectual property rights" AND AB trade OR AB "forced technology transfer"` |

Every sub-angle the user enumerates ("X, Y, Z 等") becomes at least one wave. Do not collapse
them into a single query and call it done.

---

## Phase 2: Search Loop

### CLI

```bash
# Anchor on DE + TI/AB — never drop topic word for domain-only terms
python3 scripts/ebsco_pipeline.py search "DE \"Patents\" OR DE \"Intellectual Property\" OR TI patent OR AB patent OR TI inventor" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 \
  --max 500 \
  --output ./refs/
```

### The loop (run EVERY wave from your Phase 1 plan)

Wave 1 writes the search output; waves 2+ use `--merge` to append with DOI dedup into the
SAME `search/` dir. After each wave, read the printed `Merged: N new + M existing` line —
that `N new` is your signal.

```bash
# Wave 1 (no --merge — creates the file)
python3 scripts/ebsco_pipeline.py search "<wave-1 anchor>" \
  --journals "..." --years 2022-2026 --max 500 \
  --output ./refs/{slug}/search/

# Waves 2..K (--merge — append + dedup). Run ALL planned waves.
python3 scripts/ebsco_pipeline.py search "<wave-2 anchor>" \
  --journals "..." --years 2022-2026 --max 500 --merge \
  --output ./refs/{slug}/search/
# ... wave 3, 4, 5 ...
```

### Exhaustion gate — the ONLY license to stop searching

Keep firing waves until BOTH hold:
1. **All planned sub-angle waves have run** (every angle the user named).
2. **Diminishing returns confirmed**: 2 consecutive waves each added `< 2 new` papers
   (read the `Merged: N new` line). If a wave adds ≥2, the space isn't exhausted —
   invent another adjacent angle and keep going.

Only then proceed to Phase 3. For a non-exhaustive ask (user wants "a few key papers on X"),
1-2 waves is fine — match effort to the request. But for "all / 所有 / 多多益善 / 尽可能多",
the gate above is mandatory. Narrow Top-5 corpora legitimately exhaust at low counts (e.g.
~50 hits / ~22 PDFs for patents 2022-26) — that's a valid stop ONCE the gate is met, and you
should SAY so explicitly rather than implying more exist.

### After download, loop back if warranted

If Phase 3 download surfaces a paper whose title/abstract reveals a NEW angle you didn't
search (e.g. a "quid pro quo / standard-essential patents" paper appears), add a wave for it.
The pipeline is a loop, not a line.

### What it does

1. **Session setup** (auto):
   - Try cookie injection from `~/.cache/ebsco-pipeline/session_cookies.json`
   - If cookies valid -> skip SSO, go to search
   - If cookies expired/missing -> read `~/.cufe_credentials` -> auto-fill CAS login form -> SSO login -> save cookies

2. **Search** (EBSCO API via CDP `Runtime.evaluate`):
   - POST to `https://research-ebsco-com-443.webvpn.cufe.edu.cn/api/search/v1/search?applyAllLimiters=true`
   - EBSCO query syntax with `SO`, `AND`, `OR`, `DT`, `DE`, `SU`, `FT`, `RV`, `N{n}`, `W{n}` field codes
   - Pagination: 50 per page, auto-page until `max` papers or exhausted
   - **Extracts**: subjects (DE descriptors), doc_types, page_count, publisher
   - **Facets**: journal + subject distribution auto-printed
   - `--full-text`: add `FT y` limiter (skip no-PDF papers)
   - `--peer-reviewed`: add `RV y` limiter
   - `--merge`: append to existing papers.json with DOI dedup

3. **Output**:
   - `papers.json` — full metadata with `idx`, `pdf_url`, `has_pdf`, `subjects`, `doc_types`, `page_count`, `publisher`
   - `manifest.csv` — idx, year, author, title, venue, doi, has_pdf, doc_types, subjects, source

### EBSCO query syntax

| Code | Field | Example |
|------|-------|---------|
| `TI` | Title | `TI "Patent Publication"` |
| `SO` | Source/Journal | `SO "American Economic Review"` |
| `DT` | Date range | `DT 2022-2026` |
| `AB` | Abstract | `AB patent` |
| `DE` | Descriptor/Keyword | `DE "Patents"` — **most precise** |
| `SU` | Subject | `SU innovation` |
| `AU` | Author | `AU Acemoglu` |
| `FT` | Full text available | `FT y` (also available as `--full-text` flag) |
| `RV` | Peer reviewed | `RV y` (also available as `--peer-reviewed` flag) |
| `N{n}` | Near operator | `patent N5 litigation` |
| `W{n}` | Within operator | `trade W3 patent` |

**Precision tip**: `DE "Patents"` uses EBSCO controlled vocabulary — far more precise than keyword search. Combine: `(DE "Patents" OR TI patent OR AB patent)` for recall + precision.

Full API reference: `references/ebsco_search_api.md`

### Journal filtering

EBSCO's `SO` field does **substring matching** (e.g., `SO "Journal of Political Economy"` matches "Brazilian Journal of Political Economy" too). The pipeline auto-filters results to keep only exact journal name matches. If no `--journals` specified, all results are kept.

---

## Phase 3: Download

### CLI

```bash
python3 scripts/ebsco_pipeline.py download \
  --manifest ./refs/papers.json \
  --output ./refs/ \
  --chunk-size 15 \
  --retry 2
```

### Session Batching — CRITICAL for large downloads

CDP WebSocket sessions degrade over time (connection drops, eval timeouts). The **`downloaded.json` sidecar enables safe multi-run batching** — each run skips already-downloaded papers via DOI dedup, so you never re-download.

**Stall prevention**: each PDF fetch has a 30s `AbortController` timeout. If EBSCO's server hangs, the fetch aborts (vs. blocking the entire chunk forever). Combined with CDP-level chunk timeouts, stalls self-resolve — failed fetches go to the retry queue.

| PDF count | Strategy |
|-----------|----------|
| ≤100 | Single run. `--chunk-size 15 --retry 2`. |
| 100–200 | Plan for 2 runs. Restart Chrome between runs for safety. |
| 200+ | Split into 3–4 runs of 60–80 each. Restart Chrome between batches. |

**How to batch**: run the SAME `download` command repeatedly. No separate manifest files needed.

```bash
# Run 1: downloads first ~80 PDFs, may stall. That's expected.
python3 scripts/ebsco_pipeline.py download \
  --manifest ./refs/my-project/papers.json --chunk-size 15 --retry 2

# If stalled >3 min at same count: kill (Ctrl+C), restart, run again.
# Already-downloaded papers skipped automatically via downloaded.json.
# Repeat until "All PDFs already downloaded" appears.
```

**For agents**: when downloading >100 PDFs, plan for 2–4 sequential `download` runs. Check progress with `ls pdfs/*.pdf | wc -l` between runs. If a run stalls for >3 minutes at the same PDF count, kill it and restart with the same command. The sidecar guarantees forward progress.

### What it does

1. Reads `papers.json`, finds papers with `has_pdf: true` and valid `pdf_url`
2. **DOI-based dedup**: skips papers whose DOI was already downloaded (uses `downloaded.json` sidecar). Survives filename format changes between runs.
3. **Chunked parallel download** (default 15 PDFs per chunk):
   - Each chunk: 10 concurrent fetches + base64 encode per sub-batch
   - Base64 data decoded in Python and written directly to disk
   - No reliance on Chrome's download manager — fully deterministic
   - Each chunk has its own CDP eval timeout (scales with chunk size)
4. **Retry**: transient failures (403, timeout, network errors) retried individually. HTTP 400 is NOT retried (permanent). Controlled by `--retry` (default 1).
5. **Naming**: `{FirstAuthor}_{Year}_{Title_60chars}.pdf` — HTML entities decoded in filenames
6. **Sidecar**: `downloaded.json` records `{doi: filename}` for all successful downloads

### `--chunk-size`

Controls PDFs per CDP eval call. Default 15 (base64 data is ~33% larger than raw PDF). Each chunk gets `max(120s, chunk_size * 15s)` timeout.

### `--retry`

Retry count for transient failures (HTTP 403, timeouts, network errors). Default 1. HTTP 400 errors are NOT retried (permanent — bad URL or no institutional access). Retries happen individually after all chunks complete.

### Supported formats

- PDF (application/pdf) — downloaded
- EBSCO record with `has_pdf: false` — skipped

---

## Phase 4: Manifest

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
| **Manually killing or starting Chrome** | `ensure_chrome()` uses `--headless=new` + dedicated profile. Manual `killall`/`pkill` destroys user's normal Chrome session. Pipe already handles everything. |
| Keyword search for empirical-measure topics | Papers use "innovation" not "patent" in titles |
| `curl` standalone EBSCO API calls | VPN requires SSO-bound TLS session |
| Title-only queries on EBSCO | Low recall vs. domain search with SO+DT filters |
| `window.open` for PDF download | Popup blocker + no filename control |
| iframe-based PDF download | Downloads HTML pages, not PDF content |
| Single download run for 200+ PDFs | CDP WebSocket session degrades over time — eval calls start timing out. Split into 2–4 runs via `downloaded.json` dedup (see Session Batching above). |
| Blob URL + `<a download>` click | Chrome doesn't reliably save blob URL downloads to disk. Use base64 return instead. |
| **Stopping after ONE search wave on a broad ask** | The user said "all / 多多益善". One query never covers a multi-angle topic. Run the full wave plan + exhaustion gate (Phase 2) before reporting. |
| **Asking "want more?" instead of doing more** | If the user already requested exhaustive coverage, don't bounce the decision back — fire the next wave yourself. Ask only AFTER the exhaustion gate is met. |
| Treating HTTP 400 as "search exhausted" | HTTP 400 = no full-text access for THAT paper (or recent embargo), not a corpus signal. Note it, keep searching other angles. Don't let download failures end the search loop. |

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

# 2. Search — always into refs/{project-slug}/search/
# Anchor on DE (controlled vocab) + TI/AB. Domain terms are additive recall only.
python3 scripts/ebsco_pipeline.py search "DE \"Patents\" OR DE \"Intellectual Property\" OR TI patent OR AB patent OR TI \"intellectual property\" OR TI inventor" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 --max 500 --output ./refs/my-project/search/

# 3. Download PDFs — omit --output, auto-goes to refs/my-project/pdfs/
python3 scripts/ebsco_pipeline.py download --manifest ./refs/my-project/papers.json --chunk-size 15

# 4. Results
ls ./refs/my-project/pdfs/        # PDF files
cat ./refs/my-project/manifest.csv  # Paper metadata
