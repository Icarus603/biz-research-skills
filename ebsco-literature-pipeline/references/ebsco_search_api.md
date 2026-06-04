# EBSCO Search API Reference

**Base URL (via CUFE WebVPN)**: `https://research-ebsco-com-443.webvpn.cufe.edu.cn`

All requests require CUFE WebVPN session. Access via:
- **Browser** (authenticated): fetch() from a WebVPN-authenticated page
- **CDP**: Chrome DevTools Protocol `Runtime.evaluate`
- **curl**: NOT possible — VPN binds TLS session to SSO auth

---

## POST /api/search/v1/search

Primary search endpoint. Full-text search across EBSCO databases.

### Query parameters

| Param | Value | Required |
|-------|-------|----------|
| `applyAllLimiters` | `"true"` | Yes |

### Request body (JSON)

```json
{
  "query": "innovation AND DT 2022-2026",
  "profileIdentifier": "4s3yq5",
  "searchMode": "all",
  "sort": "relevance",
  "offset": 0,
  "count": 50,
  "userDirectAction": true,
  "expanders": ["fullText", "concept"],
  "filters": [
    {"id": "databases", "values": ["eoh", "bth", "edb"]},
    {"id": "sourceTypes", "values": ["160MN"]},
    {"id": "Journal", "values": ["american economic review"]}
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `query` | string | EBSCO query syntax (see below) |
| `profileIdentifier` | string | `"k3svp7"` (EBSCO-ALL), `"4s3yq5"` (BSC), `"cojp6y"` (general) |
| `searchMode` | string | `"all"` (boolean), `"smartText"` (natural language) |
| `sort` | string | `"relevance"` (only confirmed working) |
| `offset` | int | Pagination offset (0-based) |
| `count` | int | Items per page (max 50) |
| `userDirectAction` | bool | Must be `true` |
| `expanders` | string[] | `"fullText"`, `"concept"` confirmed. `"thesaurus"` returns 400 |
| `filters` | array | Facet filters. Confirmed working ids: `databases`, `sourceTypes`, `Journal`. |

### Confirmed filter values

| Filter id | Useful values | Notes |
|-----------|---------------|-------|
| `databases` | `eoh` (EconLit with Full Text), `bth` (Business Source Complete), `edb` (Complementary Index) | Use `eoh,bth,edb` for econ/business discovery. Avoid broad EBSCO-ALL noise when possible. |
| `sourceTypes` | `160MN` | Academic journals. |
| `Journal` | lowercase journal facet labels, e.g. `american economic review`, `quarterly journal of economics`, `journal of political economy`, `econometrica`, `review of economic studies` | More precise than `SO` substring matching. |

Only request-body key `filters` works. Tested and ineffective: `facetFilters`, `appliedFacets`, `selectedFacets`, `databaseIds`, top-level `sourceTypes`.

`searchMode: "smartText"` is not appropriate for Boolean queries; it treats fielded syntax as natural language and returns huge noisy result sets. Use `searchMode: "all"`.

### Query syntax (EBSCO field codes)

| Code | Field | Example |
|------|-------|---------|
| `TI` | Title | `TI "Patent Publication"` |
| `AB` | Abstract | `AB patent` |
| `SU` | Subject | `SU innovation` |
| `DE` | Descriptor/Keyword | `DE "Intellectual Property"` |
| `AU` | Author | `AU Acemoglu` |
| `SO` | Source/Journal | `SO "American Economic Review"` |
| `DT` | Date range | `DT 2022-2026` |
| `FT` | Full text available | `FT y` |
| `RV` | Peer reviewed | `RV y` |

**Boolean operators**: `AND`, `OR`, `NOT`
**Proximity operators**: `N{n}` (near), `W{n}` (within)
**Grouping**: `()` parentheses, `""` exact phrase

### Response

```json
{
  "search": {
    "totalItems": 3125,
    "query": "...",
    "dateRange": {"minDate": "18870101", "maxDate": "20260601"},
    "items": [
      {
        "id": "cdftmn7kiv",
        "an": "2065305",
        "title": {"value": "Patent Publication and Innovation", "locale": "en"},
        "abstract": {"value": "We measure how patent publication affects...", "locale": "en"},
        "doi": "10.1086/723636",
        "source": "Journal of Political Economy",
        "publicationDate": "20230701",
        "coverDate": "July 2023",
        "contributors": [
          {"name": "Hegde, Deepak", "type": "author"}
        ],
        "subjects": [
          {"name": {"value": "Innovation and Invention...", "locale": "en"}}
        ],
        "docTypes": ["Journal Article"],
        "peerReviewed": true,
        "pageCount": "59",
        "publisherName": "University of Chicago Press",
        "links": {
          "downloadLinks": [{"type": "csv"}, {"type": "pdf"}, {"type": "html"}],
          "fullTextLinks": [...],
          "exportLinks": [...],
          "bibExportLinks": [...]
        }
      }
    ],
    "facets": [
      {"id": "Journal", "label": "出版品"},
      {"id": "SubjectEDS", "label": "主題"},
      {"id": "sourceTypes", "label": "來源類型"},
      {"id": "Language", "label": "語言"},
      {"id": "Publisher", "label": "出版商"}
    ]
  },
  "placards": []
}
```

---

## GET /api/search/v1/record/{recordId}/fulltext/pdf

PDF download endpoint.

### Parameters

| Param | Value |
|-------|-------|
| `sourceRecordId` | Record ID from search result |
| `opid` | Profile identifier (e.g., `k3svp7`) |
| `intent` | `"download"` |

### Example

```
GET /api/search/v1/record/cdftmn7kiv/fulltext/pdf?sourceRecordId=cdftmn7kiv&opid=k3svp7&intent=download
```

Returns: `application/pdf` (200) or 404 if not available.

---

## GET /api/search/v1/takeout/citation/export/{recordId}/{format}

Citation export.

### Supported formats

| Format | Endpoint |
|--------|----------|
| EndNote | `/api/search/v1/takeout/citation/export/{id}/endnote?opid=k3svp7` |
| RefWorks | `/api/search/v1/takeout/citation/export/{id}/refworks?opid=k3svp7` |
| EasyBib | `/api/search/v1/takeout/citation/export/{id}/easybib?opid=k3svp7` |

BibTeX and RIS return 400 (`IllegalTargetValueException`).

---

## Profile identifiers

| Profile | Description | Typical use |
|---------|-------------|-------------|
| `k3svp7` | EBSCO-ALL | Multi-database, broad coverage. Best for economics. |
| `4s3yq5` | BSC (Business Source Complete) | Business/management focused |
| `cojp6y` | General | Default institutional access |

---

## Per-journal counts (reference)

Innovation/patent papers by journal, 2022-2026, query `(innovation OR patent OR R&D OR "intellectual property" OR inventor OR "technology adoption")`:

| Journal | Papers |
|---------|--------|
| Journal of Political Economy | 499 |
| American Economic Review | 205 |
| Quarterly Journal of Economics | 183 |
| Review of Economic Studies | 148 |
| Econometrica | 79 |
| **Total** | **1,114** |

---

## Search strategy for empirical-measure topics

**Problem**: Papers about "X" (e.g., patents) are sometimes titled about the research domain "Y" (e.g., innovation). But the topic word still appears in abstracts, subjects (DE), or as part of the title phrase.

**WRONG approach — domain-only search**: `innovation OR R&D OR "technological change"` returns hundreds of papers about firm dynamics, technology adoption, management — most unrelated to patents. Precision drops to 30-40%.

**Correct approach — anchor on controlled vocabulary, add domain terms for recall only.**

### Step 1: Identify the EBSCO `DE` descriptor for the topic

`DE` uses EBSCO's controlled vocabulary — far more precise than free-text search. Check EBSCO thesaurus for exact descriptor values:

| Topic | Primary `DE` descriptors |
|-------|--------------------------|
| Patents | `DE "Patents"`, `DE "Intellectual Property"`, `DE "Patent Law"` |
| Credit scores | `DE "Credit Ratings"`, `DE "Credit Risk"` |
| Satellite data | `DE "Remote Sensing"`, `DE "Satellites"` |

### Step 2: Build the anchor query

```
(DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent OR TI "intellectual property")
```

### Step 3: Optionally add domain terms for recall (additive only)

Only append domain terms with `OR` to catch papers that avoid the topic word entirely. NEVER replace the anchor:

```
(DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent) OR (TI inventor AND AB "R&D")
```

### Full example — patents in Top-5 econ, 2022-2026

```
(SO "American Economic Review" OR SO "Quarterly Journal of Economics" OR SO "Journal of Political Economy" OR SO "Econometrica" OR SO "Review of Economic Studies")
AND
(DE "Patents" OR DE "Intellectual Property" OR TI patent OR AB patent OR TI "intellectual property" OR TI inventor)
AND DT 2022-2026
```

### Domain supplement patterns (additive recall only, use with caution)

| Topic | Recall supplement — only add if anchor returns too few |
|-------|-------------------------------------------------------|
| Patents | `OR (TI inventor AND AB innovation)` or `OR TI "patent protection"` |
| Credit scores | `OR (TI credit AND AB score)` or `OR DE "Consumer Credit"` |
| Satellite data | `OR TI "nighttime lights"` or `OR (AB satellite AND AB deforestation)` |

Combine with journal filter: `{JOURNAL_FILTER} AND ({anchor query}) AND DT YYYY-YYYY`
