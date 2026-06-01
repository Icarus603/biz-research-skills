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
  "query": "SO \"American Economic Review\" AND innovation AND DT 2022-2026",
  "profileIdentifier": "k3svp7",
  "searchMode": "all",
  "sort": "relevance",
  "offset": 0,
  "count": 50,
  "userDirectAction": true,
  "expanders": ["fullText", "concept"]
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

**Problem**: Papers about "X" (e.g., patents) are titled about "Y" (e.g., innovation). Searching for TI "patent" misses 95%+ of relevant papers.

**Solution**: Search for the RESEARCH DOMAIN, not the measure name.

| Topic (measure) | Domain search terms |
|----------------|-------------------|
| Patents | `innovation OR R&D OR "technological change" OR "knowledge spillover" OR inventor OR "creative destruction" OR "endogenous growth"` |
| Credit scores | `"consumer credit" OR "household finance" OR "credit market" OR borrowing OR default` |
| Satellite data | `"remote sensing" OR "earth observation" OR deforestation OR agriculture OR "nighttime lights"` |

Combine with journal filter: `(SO "Journal1" OR SO "Journal2") AND (domain terms) AND DT YYYY-YYYY`
