---
name: ebsco-literature-pipeline
description: Literature discovery and bulk PDF download. PRIMARY discovery is a parallel team of 5-7 WebSearch agents (WebSearch tool ONLY — no rate-limited bibliographic APIs) that split the topic's sub-angles. EBSCO is used to RESOLVE found papers to downloadable records and to DOWNLOAD PDFs via CUFE WebVPN (multi-epoch — re-run until all PDFs land), plus a supplementary search. CRITICAL: ANY request to find, search, collect, or download academic papers IS a request to get PDFs on local disk. No "search-only" mode. Output is always PDF files + manifest.csv. Triggers on: 找论文 搜文献 下论文 文献检索 搜论文 下载论文 找文献 论文搜索 文献收集 查文献 学术搜索 期刊论文 英文文献 find papers search literature download papers get papers collect literature literature search academic papers bulk download journal articles.
---

# EBSCO Literature Pipeline

Systematic literature discovery via a **parallel web-search agent team**, then
EBSCO (CUFE WebVPN) for **record resolution + bulk PDF download**.

```
Topic
  -> Phase 0: STATUS CHECK (check existing refs/ content — NEVER skip)
  -> Phase 1: TOPIC ANALYSIS (classify, journal scope, decompose into search angles)
  -> Phase 2: WEB DISCOVERY (5-7 parallel agents search the open web — PRIMARY)
              each agent returns a JSON paper list; aggregation merges + dedups
  -> Phase 3: RESOLVE (ebsco resolve: web papers -> EBSCO records, attach pdf_url)
  -> Phase 4: EBSCO SUPPLEMENT (one EBSCO search pass to catch what web missed) [conditional]
  -> Phase 5: DOWNLOAD (MULTI-EPOCH — loop runs until ALL PDFs on disk, never one-shot)
  -> Phase 6: MANIFEST (manifest.csv + papers.json + downloaded.json sidecar)
  -> Loop back to Phase 2 if download/notes surface new angles or user says "more"
```

## Why web-search FIRST, EBSCO second

EBSCO's relevance search is **weak for discovery** — it misses papers, ranks
poorly, and its controlled vocabulary lags new topics. General web search has **far
better recall and ranking**. So:

- **Discovery = WebSearch team.** Fan out 5-7 agents, each owning a slice of the
  topic's sub-angles, all using the WebSearch tool. This is where the corpus is
  built. (No Semantic Scholar / OpenAlex / Crossref APIs — they rate-limit and 429
  under parallel load.)
- **EBSCO = resolution + download.** EBSCO's real value is the CUFE institutional
  PDF access. We map each web-found paper to its EBSCO record (by DOI, then title)
  to obtain a downloadable `pdf_url`.
- **EBSCO search = supplement only.** A single EBSCO pass catches stragglers the
  web team missed. It is NOT the primary discovery engine.

## Prime Directive: EXHAUST, don't sample

A literature request is a request to find **everything** that matches, not a sample.
For broad/exhaustive asks ("所有 / 全部 / 多多益善 / all / as many as possible /
comprehensive"), the web team MUST cover every sub-angle the user named, and you
MUST keep merging until the **exhaustion gate** (Phase 2) is met — THEN resolve,
THEN download, THEN report. Stopping after one round and asking "want more?" is a
FAILURE mode — the user already said more. Do the rounds yourself.

## Output Convention (MANDATORY)

**Every invocation MUST follow this layout. No exceptions. No ad-hoc paths.**

```
refs/
  {project-slug}/              # kebab-case, e.g. "patents-top5", "ai-labor-market"
    papers.json                # merged + EBSCO-resolved metadata (canonical)
    manifest.csv               # merged manifest for human review
    web/                       # raw web-team discovery results (pre-resolve)
      papers.json              # aggregated, deduplicated web hits
      manifest.csv
    supplement/                # EBSCO supplementary search (if run)
      papers.json
      manifest.csv
    pdfs/                      # downloaded PDFs (download command auto-creates this)
      downloaded.json          # DOI -> filename sidecar
      Author_Year_Title.pdf
```

**Rules for agents:**
1. **ALWAYS run `status` FIRST** — before any search. Check what already exists.
2. Web-team aggregation writes `refs/{slug}/web/papers.json`.
3. `ebsco resolve` reads the web/aggregated list and writes the canonical
   `refs/{slug}/papers.json` enriched with `ebsco_id` + `pdf_url`.
4. `--output` for `download` is OMITTED — it auto-derives `pdfs/` from the manifest directory.
5. Project slug: kebab-case, short, descriptive. Derived from user's request topic.
6. Never write directly into `refs/` root — always into a project subdirectory.
7. Use `--merge` on supplementary EBSCO searches to avoid overwriting.

## Prerequisites

- CUFE WebVPN credentials in `~/.cufe_credentials` (one-time setup) — needed for resolve + download
- EBSCO session cookies auto-persisted at `~/.cache/ebsco-pipeline/session_cookies.json`
- Optional API keys for richer web results: `S2_API_KEY`, `OPENALEX_POLITE_EMAIL`, `CROSSREF_POLITE_EMAIL`

### Chrome: fully automatic — DO NOT TOUCH

`ensure_chrome()` in `ebsco_pipeline.py` handles everything:

| Detail | Value |
|--------|-------|
| Mode | `--headless=new` (invisible, no GUI window) |
| Profile | `~/.cache/ebsco-pipeline/chrome-profile` (isolated from user's normal Chrome) |
| Port check | Only kills processes on port 9222, never touches user's Chrome |
| Startup | Automatic on first `resolve`, `search`, or `download` command |

**CRITICAL for agents: NEVER manually start Chrome, kill Chrome, or run `killall "Google Chrome"`. The pipeline manages its own headless Chrome instance with a dedicated profile. It does not conflict with the user's normal Chrome. Manual intervention is the ONLY thing that can break the user's session.**

### One-time setup

```bash
cat > ~/.cufe_credentials << EOF
CUFE_USERNAME=你的学号
CUFE_PASSWORD=你的密码
EOF
chmod 600 ~/.cufe_credentials
```

---

## Phase 0: Status Check (ALWAYS FIRST)

```bash
python3 scripts/ebsco_pipeline.py status refs/{project-slug}/
```

Reports: paper count, year range, venue distribution, PDF count/disk size, sidecar state. No Chrome needed.

---

## Phase 1: Topic Analysis (plan the discovery)

Classify the topic and write a **search-angle plan** the web team will execute.

| Type | Definition | Example | Strategy |
|------|-----------|---------|----------|
| **A: Direct topic** | Paper titles contain the topic word | "minimum wage", "carbon tax" | Keyword queries suffice |
| **B: Empirical measure** | Used as DATA; some titles name the RESEARCH DOMAIN | "patents" → "innovation"; "credit scores" → "consumer credit" | Topic word + domain terms |
| **C: Broad theme** | Studied but not named explicitly | "inequality", "development" | Topic synonyms + domain |

**Rule for ALL types — NEVER drop the topic word.** Domain terms are ADDITIVE recall, never a replacement.

### Journal scope

If the user names a journal list (Top-5, UTD24, FT50 — see `references/journal_lists.md`),
pass the journal name set to EVERY web agent. Web agents filter by venue; EBSCO
resolve/supplement uses the `SO "Journal"` field code.

### Decompose into search angles (MANDATORY for broad asks)

A broad topic = a UNION of narrower angles. Write 4-8 distinct angles, each anchored
on the topic but targeting a different sub-angle the user named or implied. Distribute
these angles across the web team (Phase 2). Example — "all patent-related empirical
papers in Top-5, 2022-2026":

| Angle | Focus |
|-------|-------|
| Core patents | patent, intellectual property, inventor |
| Innovation/R&D | technological innovation, patent citations, patent data |
| Litigation/licensing | patent infringement, patent licenses, patent litigation, transfer |
| Spillovers/text | knowledge spillover, technology spillover, patent text |
| Trade/IP transfer | technology transfer, trade secrets, IP rights, forced tech transfer |

Every sub-angle the user enumerates ("X, Y, Z 等") becomes at least one angle.

---

## Phase 2: Web Discovery (PRIMARY — parallel agent team)

Spawn **5-7 subagents in ONE message** (one Agent tool call each), all in parallel.
Each is a `web_search_agent` (see `agents/web_search_agent.md`) assigned a SLICE of
the angle plan.

### WebSearch ONLY — no bibliographic APIs

**Every agent uses the `WebSearch` tool and nothing else.** Do NOT use Semantic
Scholar, OpenAlex, or Crossref APIs for discovery — they are rate-limited and 429
under parallel load. WebSearch is the single discovery source. The way you get
breadth is by splitting the ANGLE PLAN across agents (not by splitting sources).

### Team composition (split the angle plan; adjust 5-7 by breadth)

| Agent | Assigned slice |
|-------|----------------|
| 1 | Angle 1 (core topic) — multiple query phrasings |
| 2 | Angle 2 |
| 3 | Angle 3 |
| 4 | Angle 4 |
| 5 | Angle 5 |
| 6 | Recent-only sweep (last 1-2 years) across all angles — catches new papers |
| 7 | Journal-targeted sweep (query each journal name × topic) — catches venue-specific hits |

If the topic has fewer than 5 angles, give some agents overlapping angles with
different query phrasings, or merge into 5 agents. Each agent runs MULTIPLE query
variants per angle and self-loops until results stop appearing — it does NOT stop at
one query.

Each agent returns a JSON array with fields: `title`, `first_author`, `year`,
`venue`, `doi`, `oa_url`, `source` (always `"websearch"`). Agents respect the
journal scope and year range.

### Aggregate (bibliography_agent)

After all web agents return, aggregate (`agents/bibliography_agent.md`): normalize
titles, dedup by DOI → title+author similarity, keep the most complete record per
paper. No bibliographic-API enrichment — EBSCO `resolve` (Phase 3) fills missing
DOIs and is the existence check. Write the merged list to
`refs/{slug}/web/papers.json` + `web/manifest.csv`.

### Exhaustion gate — the ONLY license to stop discovery

Keep dispatching web rounds until BOTH hold:
1. **Every planned angle has been searched** by at least one agent.
2. **Diminishing returns**: a fresh round of agents adds `< 2 new` unique papers
   after dedup. If a round adds ≥2, invent an adjacent angle and dispatch again.

For a non-exhaustive ask ("a few key papers on X"), 1 round is fine — match effort
to the request. For "all / 所有 / 多多益善", the gate above is mandatory.

---

## Phase 3: Resolve (web papers → EBSCO downloadable records)

Web search yields DOI/title/author but **no EBSCO `pdf_url`**. The `resolve` command
maps each web paper to its EBSCO record so the download command can fetch the PDF
through CUFE institutional access.

```bash
python3 scripts/ebsco_pipeline.py resolve \
  --manifest ./refs/{slug}/web/papers.json \
  --output ./refs/{slug}/papers.json \
  --title-threshold 0.85
```

### What it does

1. For each paper: query EBSCO by **DOI** (`DI "..."`) first, then by **title**
   (`TI "..."`) as fallback.
2. DOI hits gated by a 0.70 title cross-check (guards against a bad DOI resolving
   to an unrelated record). Title hits require Levenshtein ≥ `--title-threshold`
   (default 0.85).
3. On match: attach `ebsco_id`, `pdf_url`, `has_pdf`; fill missing DOI/venue.
4. On no match: set `ebsco_unmatched: true`, keep `oa_url` as a download fallback.
5. Writes the canonical `refs/{slug}/papers.json` + `manifest.csv`.

Read the printed `N matched EBSCO (M with PDF), K unmatched` line. Papers with no
EBSCO PDF but a valid `oa_url` will still download via the OA fallback (Phase 5).

---

## Phase 4: EBSCO Supplement (conditional)

EBSCO is a SUPPLEMENT, not the primary search. Run ONE EBSCO pass only when:
- The user wants exhaustive coverage AND
- You suspect the web team missed EBSCO-indexed venues (e.g. an unmatched rate that
  seems high, or a niche journal).

```bash
# Anchor on DE (controlled vocab) + TI/AB. Merge into the supplement dir.
python3 scripts/ebsco_pipeline.py search "DE \"Patents\" OR DE \"Intellectual Property\" OR TI patent OR AB patent OR TI inventor" \
  --journals "American Economic Review,Quarterly Journal of Economics,Journal of Political Economy,Econometrica,Review of Economic Studies" \
  --years 2022-2026 --max 500 \
  --output ./refs/{slug}/supplement/
```

Supplement results already carry EBSCO `pdf_url` (no resolve needed). Merge them into
the canonical `refs/{slug}/papers.json` (dedup by DOI / ebsco_id) before download.

### EBSCO query syntax (for supplement + resolve internals)

| Code | Field | Example |
|------|-------|---------|
| `TI` | Title | `TI "Patent Publication"` |
| `SO` | Source/Journal | `SO "American Economic Review"` |
| `DT` | Date range | `DT 2022-2026` |
| `AB` | Abstract | `AB patent` |
| `DE` | Descriptor/Keyword | `DE "Patents"` — **most precise** |
| `DI` | DOI | `DI "10.1086/723636"` |
| `AU` | Author | `AU Acemoglu` |
| `FT` | Full text available | `FT y` (also `--full-text`) |
| `RV` | Peer reviewed | `RV y` (also `--peer-reviewed`) |
| `N{n}` / `W{n}` | Near / Within | `patent N5 litigation` |

EBSCO `SO` does **substring matching**; the pipeline auto-filters to exact journal
matches. Full reference: `references/ebsco_search_api.md`.

---

## Phase 5: Download — MULTI-EPOCH, run until ZERO remain

Download priority: **EBSCO `pdf_url`** (institutional, primary) → **`oa_url`**
(open-access web fallback for EBSCO-unmatched papers).

> **READ THIS FIRST — download is NEVER one-and-done.**
>
> A single `download` run almost NEVER fetches every PDF. The CDP WebSocket session
> degrades over time, EBSCO's server stalls on individual PDFs, and chunks time out.
> **One run = one epoch.** You MUST run multiple epochs and keep going until the
> count on disk stops rising AND every downloadable paper is accounted for. Stopping
> after one run because "it finished" or "it got most of them" is a FAILURE mode —
> the user wants ALL the PDFs, not most.

### The download loop (MANDATORY — follow exactly)

The `downloaded.json` sidecar makes every run resumable: it records `{doi: filename}`
and skips already-downloaded papers via DOI dedup. So re-running the SAME command is
always safe and always makes forward progress.

**Step 1 — compute the target.** How many papers are downloadable?
```bash
python3 -c "import json; p=json.load(open('refs/{slug}/papers.json')); print(sum(1 for x in p if x.get('pdf_url') or x.get('oa_url')))"
```
Call this `TARGET`.

**Step 2 — run an epoch:**
```bash
python3 scripts/ebsco_pipeline.py download \
  --manifest ./refs/{slug}/papers.json \
  --chunk-size 15 --retry 2
```
`--output` is omitted — auto-derives `refs/{slug}/pdfs/`.

**Step 3 — count what's on disk:**
```bash
ls refs/{slug}/pdfs/*.pdf | wc -l
```

**Step 4 — decide:**
- If on-disk count `>= TARGET` → DONE. Report completion.
- If the run printed **"All PDFs already downloaded"** → DONE (the remainder are
  permanent HTTP-400 failures with no full-text access; report them explicitly).
- **Otherwise → run another epoch (back to Step 2).** Forward progress is guaranteed
  by the sidecar. Keep looping.

**Stall handling.** If an epoch hangs >3 min at the same `[download] N/M` line, kill
it (Ctrl+C) and start the next epoch immediately — already-downloaded papers are
skipped, so you lose nothing. A killed epoch still counts; just run the next one.

**Stop ONLY when one of these is true:**
1. On-disk PDF count reached `TARGET`, OR
2. Two consecutive epochs each added **0 new PDFs** AND the run reported the
   remainder as permanent (HTTP 400 / no full-text access).

Do NOT stop because "a lot downloaded" or "the command returned." Loop until the gate.

### Epoch budget by corpus size (minimum epochs to plan for)

| Downloadable PDFs | Plan for | Notes |
|-------------------|----------|-------|
| ≤100 | 2-3 epochs | Even small sets stall on a few PDFs — expect a second pass. |
| 100–200 | 4-6 epochs | Session degrades mid-run; restart between epochs. |
| 200+ | 6-10 epochs | Run in waves; the count climbs each epoch until it plateaus. |

These are MINIMUMS, not targets — keep going past them if PDFs are still arriving.

### What it does

1. Reads `papers.json`, picks papers with `pdf_url` OR `oa_url`.
2. **DOI-based dedup** via `downloaded.json` sidecar — survives filename changes.
3. **Chunked parallel download** (default 15/chunk, 10 concurrent fetches, base64 → disk).
4. **Retry**: transient failures (403, timeout, network) retried; HTTP 400 not retried.
5. **Naming**: `{FirstAuthor}_{Year}_{Title_60chars}.pdf`.
6. Per-PDF 30s `AbortController` timeout prevents stalled chunks.

---

## Phase 6: Manifest

`resolve` and `search` both generate `manifest.csv` automatically.

**manifest.csv** (post-resolve):
```
idx,year,first_author,title,venue,doi,has_pdf,ebsco_id,ebsco_unmatched,oa_url,source
001,2023,Hegde,Patent Publication and Innovation,Journal of Political Economy,10.1086/723636,True,cdftmn7kiv,False,,websearch
```

`papers.json` includes full metadata + `ebsco_id`, `pdf_url`, `oa_url` per paper.

---

## Architecture

### CDP Client (`scripts/cdp_client.py`)
Pure-stdlib WebSocket CDP client. Zero deps. `Page.navigate`, `Runtime.evaluate`,
`Network.getCookies/setCookie`.

### Pipeline (`scripts/ebsco_pipeline.py`)
CLI: `status`, `resolve`, `search`, `download`.
- `resolve` — web papers → EBSCO records (DOI then title match), attach pdf_url
- `search` — EBSCO supplementary search
- `download` — EBSCO pdf_url + OA fallback, chunked, sidecar dedup
- Session auto-management: cookie injection → SSO fallback → cookie persistence

### Web team (`agents/web_search_agent.md`, `agents/bibliography_agent.md`)
Parallel WebSearch discovery agents + aggregation/dedup.

### References
`references/ebsco_search_api.md` — EBSCO API. `references/journal_lists.md` — scopes.
`references/{semantic_scholar,openalex,crossref}_api_protocol.md` — legacy API notes,
NOT used for discovery (kept for reference only; WebSearch-only policy supersedes them).

---

## Anti-Patterns

| Approach | Why It Fails |
|----------|-------------|
| **Using EBSCO search as the PRIMARY discovery engine** | EBSCO recall/ranking is weak. Discover via the web team; EBSCO is for resolve + download + supplement only. |
| **Skipping resolve, feeding web papers.json straight to download** | Web papers have no EBSCO `pdf_url`. Without resolve, only OA-url papers download — most institutional PDFs are lost. Run `resolve` first. |
| **Manually killing or starting Chrome** | `ensure_chrome()` uses `--headless=new` + dedicated profile. Manual `killall` destroys the user's normal Chrome session. |
| **One web agent / one query** | A broad topic is a union of angles. Fan out 5-7 agents across sources + angles; loop until the exhaustion gate. |
| `curl` standalone EBSCO API calls | VPN binds SSO to the TLS session. |
| **Stopping after ONE discovery round on a broad ask** | The user said "all / 多多益善". Run the full angle plan + exhaustion gate before resolving. |
| **Asking "want more?" instead of doing more** | If the user requested exhaustive coverage, fire the next round yourself. Ask only AFTER the gate is met. |
| **Stopping download after ONE epoch** | One run never fetches every PDF — CDP sessions degrade, EBSCO stalls, chunks time out. Run epoch after epoch (sidecar resumes) until on-disk count = TARGET or two epochs add 0 new. See Phase 5. |
| **Treating a hung download as "done"** | A stall ≠ completion. Kill (Ctrl+C) and run the next epoch — already-downloaded papers are skipped. |
| Treating HTTP 400 on download as "exhausted" | HTTP 400 = no full-text access for THAT paper, not a corpus signal. Note it, keep going. |
| `window.open` / iframe / blob-click PDF download | Popup blockers, HTML-not-PDF, unreliable disk writes. Pipeline uses base64 return. |

---

## Quick Start

```bash
# 0. One-time: credentials (for resolve + download)
echo 'CUFE_USERNAME=学号' > ~/.cufe_credentials
echo 'CUFE_PASSWORD=密码' >> ~/.cufe_credentials
chmod 600 ~/.cufe_credentials

# 1. Status
python3 scripts/ebsco_pipeline.py status refs/my-project/

# 2. DISCOVER — spawn 5-7 web_search_agent subagents in parallel (Agent tool),
#    aggregate via bibliography_agent → refs/my-project/web/papers.json

# 3. RESOLVE — map web papers to EBSCO downloadable records
python3 scripts/ebsco_pipeline.py resolve \
  --manifest ./refs/my-project/web/papers.json \
  --output ./refs/my-project/papers.json

# 4. (optional) SUPPLEMENT — one EBSCO pass for stragglers, merge into papers.json
python3 scripts/ebsco_pipeline.py search "DE \"Patents\" OR TI patent OR AB patent" \
  --journals "American Economic Review,Quarterly Journal of Economics" \
  --years 2022-2026 --output ./refs/my-project/supplement/

# 5. DOWNLOAD — MULTI-EPOCH. Re-run until on-disk count stops rising (see Phase 5).
TARGET=$(python3 -c "import json;p=json.load(open('refs/my-project/papers.json'));print(sum(1 for x in p if x.get('pdf_url') or x.get('oa_url')))")
while [ "$(ls refs/my-project/pdfs/*.pdf 2>/dev/null | wc -l | tr -d ' ')" -lt "$TARGET" ]; do
  python3 scripts/ebsco_pipeline.py download --manifest ./refs/my-project/papers.json --chunk-size 15 --retry 2
  echo "on disk: $(ls refs/my-project/pdfs/*.pdf 2>/dev/null | wc -l) / $TARGET"
  # break out manually if two epochs add 0 new and remainder is HTTP-400 permanent
done

# 6. Results
ls ./refs/my-project/pdfs/
cat ./refs/my-project/manifest.csv
```
