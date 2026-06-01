---
name: ebsco-literature-pipeline
description: Literature discovery and bulk PDF download pipeline. Combines systematic multi-API academic search (Semantic Scholar, OpenAlex, Crossref, WebSearch) with EBSCO/CUFE-VPN download and open-access direct download. CRITICAL INTENT RULE: Any request to find, search, collect, or download academic papers IS a request to get PDFs on local disk — not just metadata. No "search-only" mode. Output is always PDF files + manifest.csv. Triggers on: "find papers on X", "search literature on X", "download papers about X", "get me papers on X", "collect literature for X", or any research topic that implies needing paper PDFs.
---

# EBSCO Literature Pipeline

Systematic literature discovery + bulk PDF download.

```
Topic
  → Phase 1: PARALLEL SEARCH (6+ subagents concurrently search S2/OpenAlex/Crossref/WebSearch/Google Scholar)
  → Phase 1b: AGGREGATE (dedup + triangulation + merge → verified paper list)
  → Phase 2: EBSCO Session
  → Phase 3: Acquisition  (OA direct curl + EBSCO TI-exact lookup + window.open)
  → Phase 4: Dedup + Move + Rename + manifest.csv + not_found.txt
```

## Prerequisites

- Chrome DevTools MCP running
- CUFE WebVPN browser session

---

## Phase 1a: Parallel Literature Search (6+ subagents concurrently)

**CRITICAL**: Search is parallel, not serial. Spawn ALL subagents below in ONE message. Minimum 6 agents. No upper limit — more agents = better coverage. All agents run concurrently.

**Input**: user's research topic — treat directly as the Research Question. Skip deep-research Phase 1 RQ scoping entirely.

**Journal scope** — check if user specified a scope. If not, ask once:
"Search all journals, or restrict to a specific list? (All journals / Economics Top-5 / UTD24 / FT50 / Other)"

Apply the corresponding filter from `references/journal_lists.md` to all queries. If user says "all journals", no filter.

For each subagent below, include the journal filter (if any) in the query instructions. When a journal list is active, append venue/keyword constraints to the search queries.

---

### Spawn these 7 subagents IN PARALLEL (one message, all Agent tool calls):

#### Subagent 1: Semantic Scholar API Search
```
Use Semantic Scholar API to find papers on: {topic} [{journal_filter if any}]

Search strategy:
1. Formulate 3-5 different keyword combinations (synonyms, related terms, different phrasings)
2. For each combination, query: GET https://api.semanticscholar.org/graph/v1/paper/search?query={url_encoded}&limit=30&fields=title,authors,year,externalIds,venue,publicationDate,openAccessPdf
3. Merge all results, deduplicate by paperId
4. Also try the "bulk" endpoint if rate limit allows: POST /graph/v1/paper/search/bulk

Rate limit: 1 req/s (no key), 10 req/s (with S2_API_KEY env var). Respect with sleep.

Return ONLY a JSON array. For each paper include:
- title, first_author (first author name only), year, venue (journal name), doi, oa_url (openAccessPdf.url if available), s2_id (paperId), source: "s2"
```

#### Subagent 2: OpenAlex API Search
```
Use OpenAlex API to find papers on: {topic} [{journal_filter if any}]

Search strategy:
1. Formulate 3-5 keyword combinations
2. Query: GET https://api.openalex.org/works?search={url_encoded}&per-page=30&select=id,title,authorships,publication_year,doi,primary_location,open_access
3. If journal filter active, also filter by primary_location.source.display_name
4. For each hit, extract oa_url from open_access.oa_url if available

Rate limit: 10 req/s with mailto param. Add &mailto=user@example.com to URL.

Return ONLY a JSON array. For each paper include:
- title, first_author, year, venue, doi, oa_url, s2_id (null — OpenAlex IDs differ), source: "openalex"
```

#### Subagent 3: Crossref API Search
```
Use Crossref API to find papers on: {topic} [{journal_filter if any}]

Search strategy:
1. Formulate 3-5 keyword combinations
2. Query: GET https://api.crossref.org/works?query={url_encoded}&rows=30&filter=type:journal-article
3. If journal filter, add &filter=issn:{issn_list} or filter by container-title in results

Rate limit: ~5 req/s (anonymous). Add User-Agent with mailto.

Return ONLY a JSON array. For each paper include:
- title (first element of title array), first_author (given + family of first author), year (from issued.date-parts[0][0]), venue (container-title), doi, oa_url (from link with content-type: application/pdf), s2_id (null), source: "crossref"
```

#### Subagent 4: WebSearch #1 — Broad Academic Search
```
Use WebSearch tool to find academic papers on: {topic} [{journal_filter if any}]

Search strategy — run ALL of these queries (minimum 5):
1. "{topic} academic paper site:scholar.google.com OR site:semanticscholar.org"
2. "{topic} journal article DOI"
3. "{topic} research paper PDF"
4. "{topic} literature review"
5. "{topic} empirical study"
6. "{topic} {synonym1}"
7. "{topic} {synonym2}"

For each search result page, use WebFetch to extract paper titles, authors, years, venues, and DOIs.
Prioritize .edu, .org, academic publisher domains.

Return ONLY a JSON array. For each paper include:
- title, first_author, year, venue, doi, oa_url (direct PDF link if found), s2_id (null), source: "websearch1"
```

#### Subagent 5: WebSearch #2 — Complementary Keywords & Grey Literature
```
Use WebSearch tool to find academic papers on: {topic} [{journal_filter if any}]

Search strategy — use DIFFERENT keywords from Subagent 4. Run ALL:
1. "{topic} SSRN working paper"
2. "{topic} NBER working paper"
3. "{topic} RePEc"
4. "{topic} conference proceedings"
5. "{topic} dissertation thesis"
6. "{topic} recent 2024 2025 2026"
7. "{topic} seminal influential"

Also search in Chinese if topic is relevant: "{topic_chinese} 学术论文"

Return ONLY a JSON array. For each paper include:
- title, first_author, year, venue, doi, oa_url, s2_id (null), source: "websearch2"
```

#### Subagent 6: WebSearch #3 — Top Journal Targeted Search
```
Use WebSearch tool to find papers on: {topic} [{journal_filter if any}]

IF journal filter is active:
  For EACH journal in the filter list, search: "{topic} site:{journal_domain}" or "{topic} {journal_name}"
  Example: "{topic} site:aeaweb.org" for AER

IF no journal filter (all journals):
  Search top journals by field relevance:
  - Economics: "site:aeaweb.org OR site:journals.uchicago.edu/jpe {topic}"
  - Finance: "site:onlinelibrary.wiley.com/journal/15406261 {topic}"
  - Management: "site:journals.aom.org {topic}"
  - General: "{topic} Q1 journal top tier"

Return ONLY a JSON array. For each paper include:
- title, first_author, year, venue, doi, oa_url, s2_id (null), source: "websearch3"
```

#### Subagent 7: Google Scholar WebFetch
```
Use WebFetch to search Google Scholar for: {topic} [{journal_filter if any}]

Strategy:
1. WebFetch: https://scholar.google.com/scholar?q={url_encoded_topic}&num=20&as_sdt=0,5
2. Parse results: titles, authors, years, venues, citation counts
3. Try 2-3 keyword variations
4. If blocked/hit CAPTCHA, fall back to WebSearch with "site:scholar.google.com {topic}"

Return ONLY a JSON array. For each paper include:
- title, first_author, year, venue, doi, oa_url, s2_id (null), source: "googlescholar"
```

---

### Output Format (ALL subagents MUST use exactly this):
```json
[
  {
    "title": "The Impact of AI on Labor Markets: Evidence from Online Job Postings",
    "first_author": "Acemoglu",
    "year": 2024,
    "venue": "American Economic Review",
    "doi": "10.1257/aer.20231234",
    "oa_url": "https://doi.org/10.1257/aer.20231234",
    "s2_id": "abc123def456",
    "source": "s2"
  }
]
```

ALL fields are strings except year (int) and s2_id (string|null). Unknown fields → null. Empty author → "Unknown".

---

## Phase 1b: Aggregate & Deduplicate

After ALL subagents return, spawn the aggregation agent:

Read and execute `agents/bibliography_agent.md` as the Aggregation Agent.

**Input to aggregation agent**:
1. The combined JSON arrays from all 7 subagents
2. The original topic and journal filter
3. Reference files: `references/semantic_scholar_api_protocol.md`, `references/openalex_api_protocol.md`, `references/crossref_api_protocol.md`

**What it does**:
1. Merge all paper lists into one flat array
2. Normalize titles (lowercase, strip punctuation, remove extra whitespace)
3. Deduplicate by this priority chain:
   a. Same DOI → merge, keep most complete record
   b. Same S2 ID → merge
   c. Title similarity ≥ 0.85 (Levenshtein ratio) AND same first_author → merge
   d. Title similarity ≥ 0.90 → merge (with warning)
4. Run three-index triangulation:
   - For each paper, verify existence across S2, OpenAlex, and Crossref APIs
   - Paper found in ≥ 1 index → `not_found: false`
   - Paper found in 0 indexes → `not_found: true`
5. Sort by year descending, then first_author
6. Assign sequential idx starting from 1
7. Enrich: for papers missing oa_url, try to find one via S2 openAccessPdf field

**Output** — structured paper list:
```
{
  idx: int,
  title: string,
  first_author: string,
  year: int,
  venue: string,
  doi: string | null,
  oa_url: string | null,
  s2_id: string | null,
  not_found: bool,
  sources: ["s2", "websearch1", ...]  # which subagents found this paper
}
```

Show user the list (idx + title + first_author + year + venue, N papers total). Ask: "Found N papers (M unique after dedup). Proceed with download?"

---

## Phase 2: Establish EBSCO Session

**Never ask user about login. Check it yourself.**

```
Step 1: navigate_page → http://lib-443.webvpn.cufe.edu.cn/
Step 2: evaluate_script → window.location.href = 'https://research.ebsco.com/c/k3svp7/search'
Step 3: evaluate_script → () => window.location.href
```

- URL contains `research.ebsco.com` → proceed
- URL contains `idp.cufe.edu.cn` → SSO triggered. Go back to VPN portal, retry Step 2.

**CRITICAL: Never `navigate_page` directly to `research.ebsco.com`.** JS jump via VPN portal carries the session cookie; direct navigation does not.

---

## Phase 3: Acquisition

Two mutually exclusive tracks per paper — no paper enters both. Track A runs first; only papers Track A cannot handle go to Track B.

### OA URL Classification (run before Track A)

For each paper with `oa_url`, classify the URL:

**Published version** (use Track A):
- DOI-based URL (contains `doi.org`)
- Publisher domain (e.g. `aeaweb.org`, `journals.uchicago.edu`, `onlinelibrary.wiley.com`, etc.)

**Preprint / working paper** (skip Track A → go directly to Track B):
- `arxiv.org`, `ssrn.com`, `nber.org`, `repec.org`, `bfi.uchicago.edu`, `iza.org`, `brookings.edu`, `imf.org/en/Publications/WP`, or any URL containing `working-paper`, `wp`, `discussion-paper`

**Exception**: if the user explicitly requests working papers or preprints, skip this filter and use any `oa_url`.

### Track A: OA Direct Download (published versions only)

Papers with a classified published `oa_url` and `not_found: false`:

```bash
mkdir -p "{target_dir}"
cd "{target_dir}"
for paper in oa_published_papers:
    curl -L --max-time 30 -s -o "oa_{idx:03d}.pdf" "{oa_url}"
    # Check file size — < 10KB means download failed (login wall, error page)
    if [ $(stat -f%z "oa_{idx:03d}.pdf" 2>/dev/null || stat -c%s "oa_{idx:03d}.pdf") -lt 10240 ]; then
        rm "oa_{idx:03d}.pdf"
        # Mark as oa_failed → do NOT fall back to EBSCO, mark not_found
    fi
done
```

Mark: `source: oa` (success). On failure: mark `source: not_found` — do not fall back to EBSCO.

### Track B: EBSCO TI Exact Lookup

Papers that are:
- `not_found: false`, AND
- no `oa_url`, OR `oa_url` classified as preprint/working paper

Excluding: `not_found: true`, `source: oa` (already downloaded).

#### Step 3b-1: Per-paper EBSCO search + collect pdfUrls

```js
async () => {
  const API = 'https://research.ebsco.com/api/search/v1/search?applyAllLimiters=true';
  const papers = [...]; // [{idx, title}, ...] — Track B only

  const results = [];
  for (const p of papers) {
    const resp = await fetch(API, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        query: `TI "${p.title}"`,
        profileIdentifier: 'k3svp7',
        expanders: ['fullText', 'concept'], filters: [],
        searchMode: 'all', sort: 'relevance',
        offset: 0, count: 5, userDirectAction: true
      })
    }).then(r => r.json());

    const hit = (resp?.search?.items || [])[0];
    const pdfUrl = hit?.links?.downloadLinks?.find(l => l.type === 'pdf')
      ? `https://research.ebsco.com/api/search/v1/record/${hit.id}/fulltext/pdf?sourceRecordId=${hit.id}&opid=k3svp7&intent=download&lang=zh-TW`
      : null;

    results.push({ idx: p.idx, pdfUrl, ebsco_hit: !!hit });
    await new Promise(r => setTimeout(r, 300));
  }
  return results;
}
```

Papers with `pdfUrl: null` → mark `source: not_found`.

#### Step 3b-2: Bulk download via window.open

```js
async () => {
  const urls = [...]; // all pdfUrl values from Step 3b-1
  for (let round = 0; round < 5; round++) {
    urls.forEach(url => { try { window.open(url, '_blank'); } catch(e) {} });
    await new Promise(r => setTimeout(r, 3000));
  }
  return { done: true };
}
```

Check progress after each round:
```bash
ls ~/Downloads/EBSCO*.pdf | wc -l
```
Stop when count stable for 2 consecutive rounds.

---

## Phase 4: Finalize

### Determine target directory

- User specified a path → use it
- `refs/` exists in current working directory → suggest it, confirm with user
- Otherwise ask: "Where should PDFs be saved?"

### Move & dedup

```bash
mv ~/Downloads/EBSCO*.pdf "{target_dir}/"
```

Dedup by exact byte size:

```python
import os
from collections import defaultdict

os.chdir("{target_dir}")
groups = defaultdict(list)
for f in os.listdir('.'):
    if f.endswith('.pdf'):
        groups[os.path.getsize(f)].append(f)
for sz, grp in groups.items():
    for dup in grp[1:]:
        os.remove(dup)
```

### Rename to sequential numbers

```bash
i=1
for f in *.pdf; do
  mv "$f" "$(printf '%03d' $i).pdf"
  i=$((i+1))
done
```

### Generate manifest.csv

```python
import csv, os

papers = [...]  # full Phase 1 list

with open("{target_dir}/manifest.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["idx","year","first_author","title","venue","doi","oa_url","source"])
    for p in papers:
        if p["not_found"]:
            source = "not_found"
        elif p.get("oa_url"):
            source = "oa"
        elif p.get("ebsco_hit"):
            source = "ebsco"
        else:
            source = "not_found"
        w.writerow([
            f"{p['idx']:03d}", p["year"], p["first_author"],
            p["title"], p["venue"], p.get("doi",""), p.get("oa_url",""), source
        ])
```

### Generate not_found.txt

```python
not_found = [p for p in papers if p.get("source") == "not_found"]
with open("{target_dir}/not_found.txt", "w") as f:
    for p in not_found:
        f.write(f"{p['year']} | {p['first_author']} | {p['title']}\n")
        if p.get("doi"):
            f.write(f"  DOI: {p['doi']}\n")
```

---

## Final Summary

```
Discovery:   N papers  (7 parallel subagents: S2 + OpenAlex + Crossref + WebSearch×3 + Google Scholar)
Downloaded:  X PDFs    (Y via OA direct, Z via EBSCO)
Not found:   M papers  → not_found.txt
Location:    {target_dir}/
Manifest:    {target_dir}/manifest.csv
```

Note: manifest row order = bibliography discovery order. PDF filenames (001.pdf...) are assigned by download completion order — not directly mapped to manifest rows. The manifest documents what was discovered; the PDFs are the acquired subset.

---

## Anti-Patterns

| Approach | Why It Fails |
|----------|-------------|
| `curl`/Python standalone EBSCO API calls | 401 — auth tied to browser VPN session |
| `navigate_page` directly to `research.ebsco.com` | Always triggers SSO |
| `navigate_page` for PDF URLs | Timeout, unreliable |
| `fetch` + blob + `<a download>` | MCP Chrome doesn't save blob files |
| pdftotext for dedup or rename | Font encoding garbles text |
| Size-tolerance dedup | Different papers can have similar byte counts |
| Moving files mid-download | Breaks Chrome sequential naming |
| Broad EBSCO keyword search | Low recall vs. TI exact-title per-paper lookup |

---

## Files

| File | Purpose |
|------|---------|
| `agents/bibliography_agent.md` | Aggregation agent — dedup, triangulation, merge of parallel search results |
| `references/semantic_scholar_api_protocol.md` | S2 API patterns, rate limits, dedup via S2 ID |
| `references/openalex_api_protocol.md` | OpenAlex API patterns |
| `references/crossref_api_protocol.md` | Crossref API patterns |
