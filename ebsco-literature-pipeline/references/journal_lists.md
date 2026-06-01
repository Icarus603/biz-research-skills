# Journal Scope Lists

Use these when the user wants to restrict search to a specific journal set.
Pass the relevant SO filter to bibliography_agent and to EBSCO queries.

---

## Economics Top-5

The five general-interest journals in economics with highest prestige.

```
SO "American Economic Review"
SO "Quarterly Journal of Economics" OR SO "The Quarterly Journal of Economics"
SO "Journal of Political Economy"
SO "Econometrica"
SO "Review of Economic Studies"
```

**EBSCO filter string:**
```
(SO "American Economic Review" OR SO "Quarterly Journal of Economics" OR SO "The Quarterly Journal of Economics" OR SO "Journal of Political Economy" OR SO "Econometrica" OR SO "Review of Economic Studies")
```

**S2/OpenAlex venue filter keywords:**
`American Economic Review`, `Quarterly Journal of Economics`, `Journal of Political Economy`, `Econometrica`, `Review of Economic Studies`

---

## UTD24

24 journals used by UT Dallas to rank business school research output.
Covers: accounting, finance, information systems, management, marketing, operations management.

| # | Journal | Abbrev |
|---|---------|--------|
| 1 | Accounting Review | AR |
| 2 | Journal of Accounting and Economics | JAE |
| 3 | Journal of Accounting Research | JAR |
| 4 | Journal of Finance | JF |
| 5 | Journal of Financial Economics | JFE |
| 6 | Review of Financial Studies | RFS |
| 7 | Information Systems Research | ISR |
| 8 | Journal of Management Information Systems | JMIS |
| 9 | MIS Quarterly | MISQ |
| 10 | Academy of Management Journal | AMJ |
| 11 | Academy of Management Review | AMR |
| 12 | Administrative Science Quarterly | ASQ |
| 13 | Journal of International Business Studies | JIBS |
| 14 | Journal of Management | JOM |
| 15 | Journal of Management Studies | JMS |
| 16 | Management Science | MS |
| 17 | Organization Science | OS |
| 18 | Strategic Management Journal | SMJ |
| 19 | Journal of Consumer Research | JCR |
| 20 | Journal of Marketing | JM |
| 21 | Journal of Marketing Research | JMR |
| 22 | Marketing Science | MktSci |
| 23 | Journal of Operations Management | JOM-Ops |
| 24 | Manufacturing & Service Operations Management | MSOM |

**EBSCO filter string (paste directly):**
```
(SO "Accounting Review" OR SO "Journal of Accounting and Economics" OR SO "Journal of Accounting Research" OR SO "Journal of Finance" OR SO "Journal of Financial Economics" OR SO "Review of Financial Studies" OR SO "Information Systems Research" OR SO "Journal of Management Information Systems" OR SO "MIS Quarterly" OR SO "Academy of Management Journal" OR SO "Academy of Management Review" OR SO "Administrative Science Quarterly" OR SO "Journal of International Business Studies" OR SO "Journal of Management" OR SO "Journal of Management Studies" OR SO "Management Science" OR SO "Organization Science" OR SO "Strategic Management Journal" OR SO "Journal of Consumer Research" OR SO "Journal of Marketing" OR SO "Journal of Marketing Research" OR SO "Marketing Science" OR SO "Journal of Operations Management" OR SO "Manufacturing & Service Operations Management")
```

---

## FT50

50 journals used by the Financial Times to rank business school research.
Superset of UTD24; adds additional journals across all business disciplines.

Key additions over UTD24 (selected):
- Journal of Applied Psychology
- Journal of Business Ethics
- Journal of Business Venturing
- Journal of Financial and Quantitative Analysis
- Journal of Political Economy *(overlaps Econ Top-5)*
- Organizational Behavior and Human Decision Processes
- Production and Operations Management
- Rand Journal of Economics
- Research Policy
- Review of Accounting Studies
- Review of Economic Studies *(overlaps Econ Top-5)*
- Strategic Entrepreneurship Journal

Full list: https://www.ft.com/content/3405a512-5cbb-11e1-8f1f-00144feabdc0

---

## Usage in Queries

When user specifies a scope, prepend the journal filter to the topic query with AND:

```
{JOURNAL_FILTER} AND ({topic keywords})
```

Example — AI labor market in Top-5 econ:
```
(SO "American Economic Review" OR SO "Quarterly Journal of Economics" OR SO "The Quarterly Journal of Economics" OR SO "Journal of Political Economy" OR SO "Econometrica" OR SO "Review of Economic Studies") AND (TI "artificial intelligence" OR TI "automation" OR DE "labor market")
```
