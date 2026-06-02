---
name: data-feasibility
description: Assess data availability and acquisition feasibility for a research topic or specific variables. Evaluates commercial databases, public data sources, web scraping options, and alternative data construction strategies. Use when the user wants to know if data exists for their research idea, which databases to use, whether scraping is feasible, or how to construct a key variable. Triggers on: "数据在哪里", "这个变量怎么找", "有没有数据做这个", "data feasibility", "can I get data for X", "how to get data on X", "数据可得性", "能不能爬", "爬虫获取", "有没有现成数据", or after generating a research idea from lit-scout or deep-read.
---

# Data Feasibility

Assess data availability and acquisition strategy for a research topic or variable set.

## Input

Accept any of:
- A research topic / RQ
- A specific variable list (Y, X, controls)
- An Idea Seed from `deep-read` or `lit-scout`
- A combination

Ask user (if unclear):
1. **Research context**: China domestic / cross-country / specific industry?
2. **Time period needed**: What years? Panel or cross-section?
3. **Unit of observation**: Firm / individual / city / patent / product?
4. **Database access**: Which databases does the user currently have access to? (CSMAR / WIND / CNRDS / CFPS / other)

---

## Phase 1: Variable Decomposition

Break the research into specific data needs:

For each variable (Y, X, IV/treatment, controls, mechanism vars):
```
Variable: {name}
Type: Y / X / IV / control / mechanism
Conceptual definition: {what exactly needs to be measured}
Ideal data source: {most precise measure}
Fallback measure: {proxy if ideal not available}
```

---

## Phase 2: Database Matching

Read `references/china_databases.md`. Match each variable to available sources.

For each match, assess:

| Variable | Database | Coverage fit | Variable fit | Access | Notes |
|----------|---------|-------------|-------------|--------|-------|
| {var} | {db} | ✓/✗/partial | ✓/✗/proxy | {accessible?} | {caveat} |

**Coverage fit**: does the database cover the right years, geography, firm/individual type?
**Variable fit**: is the variable directly available, or needs construction?
**Access**: user said they have access / typical university access / requires application / commercial only

---

## Phase 3: Scraping Assessment

For variables NOT in commercial databases, evaluate scraping:

**For each scraping target:**

```
Source: {website/platform}
Data: {what can be obtained}
Method: {direct download / API / Scrapy+Selenium / browser automation}
Legal risk: Low / Medium / High
  - Low: clearly public data, no ToS restriction
  - Medium: ToS ambiguous, anti-scraping measures present
  - High: login required, explicit ToS prohibition, personal data
Technical difficulty: Low / Medium / High
Sample coverage: {can it cover the needed observation unit and time period?}
Recommendation: {proceed / caution / avoid}
```

Use WebSearch to check current accessibility of specific sources if needed.

---

## Phase 4: Alternative Construction Strategies

For variables that cannot be directly obtained, suggest construction:

- **Text-based proxies**: annual report MD&A, news sentiment, job postings → NLP
- **Satellite/remote sensing**: nighttime lights (NTL), land use → CNRDS GTA or Google Earth Engine
- **Network construction**: patent citation networks, supply chain from SAIC filings
- **Linked datasets**: merge CSMAR (firm) + CNRDS (patent) + NBS yearbook (industry) by firm code / province code
- **Difference-in-differences instrument construction**: policy shock timing from government documents / CNKI legal database

---

## Phase 5: Feasibility Verdict

Output a structured assessment:

```markdown
## Data Feasibility Report

**Research**: {RQ in one line}
**Unit**: {firm/individual/city/...} | **Period**: {years} | **Country/Region**: {scope}

### Variable Assessment

| Variable | Source | Status | Notes |
|----------|--------|--------|-------|
| {Y} | {database} | ✓ Available | {version, coverage} |
| {X} | {source} | ⚠ Proxy needed | {construction method} |
| {IV} | {source} | ✗ Requires scraping | {feasibility: medium} |
| {control} | {source} | ✓ Available | — |

### Overall Verdict

**Feasibility**: High / Medium / Low / Blocked

**Critical bottleneck**: {the single hardest variable to obtain}

**Recommended data strategy**:
1. {primary path}
2. {fallback if bottleneck unresolved}

### Acquisition Roadmap

| Task | Method | Estimated effort | Priority |
|------|--------|-----------------|---------|
| Apply for CFPS access | Registration at PKU website | 1-2 weeks | High |
| Download CNRDS patent data | Direct from CNRDS portal | 1 day | High |
| Scrape CNINF announcements | Python Scrapy | 1-2 weeks coding | Medium |
| Construct NTL measure | Google Earth Engine JS | 1 week | Low |

### Risk Flags

- {any variable that fundamentally cannot be obtained → may need to change RQ}
- {any scraping with high legal risk → recommend avoiding}
- {any database requiring lengthy application → flag timeline}
```

---

## Phase 6: Save to Project

If a project exists (from `biz-research-scaffold`):
- **Check `{project}/data/README.md` first.** If it has existing content (not just scaffold stub), preserve it — append the new feasibility report under a `## Data Feasibility ({date})` header. Never overwrite existing data documentation.
- If `data/README.md` is still just the scaffold stub (empty or template), replace it with the full report.
- Append a one-line summary (date + verdict + critical bottleneck) to `{project}/refs/{slug}/notes/digest.md` if it exists. If no project slug, use `{project}/refs/notes/digest.md`.
