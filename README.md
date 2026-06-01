# Research Skill Set

A suite of Claude Code skills for academic research in business and social science fields. Covers the full workflow from project setup through topic selection, literature management, and presentation.

## Workflow

```
biz-research-scaffold          — set up project
       ↓
ebsco-literature-pipeline      — discover & download papers → refs/
       ↓
lit-scout                      — parallel digest of all PDFs → refs/notes/
       ↓
deep-read                      — deep read selected papers → refs/notes/deep_*.md
       ↓
paper-note                     — typeset reading note as PDF → refs/notes/{slug}_note/
       ↓
data-feasibility               — assess data availability → data/README.md
       ↓
topic-scout                    — Socratic topic selection → refs/notes/topic_proposal.md
       ↓
minimal-beamer                 — build presentation slides → output/figures/
```

---

## Skills

### `biz-research-scaffold`
Scaffold a research repository for economics, finance, management, or any business/social science field.

- Detects OS (bash / pwsh) and installed tools (Stata, R, Python, git)
- Asks only what is unclear via `AskUserQuestion`
- Runs a deterministic shell script — no LLM-generated file operations

**Output directory structure:**
```
{project}/
├── data/raw/  processed/  README.md
├── code/  README.md
├── output/tables/  figures/  logs/
├── refs/  notes/
├── paper/  README.md
├── .gitignore
└── README.md
```

---

### `ebsco-literature-pipeline`
Systematic literature discovery and bulk PDF download.

- **Discovery**: Semantic Scholar + OpenAlex + Crossref + WebSearch via `bibliography_agent`
- **Download**: published OA versions via `curl`; EBSCO/CUFE-VPN for the rest
- **Journal scope**: All / Economics Top-5 / UTD24 / FT50 (see `references/journal_lists.md`)
- **Output**: `refs/*.pdf` + `refs/manifest.csv` + `refs/not_found.txt`

---

### `lit-scout`
Rapid parallel literature digest for topic scouting.

- Spawns one subagent per PDF (all in parallel)
- Each subagent writes a structured note using `templates/paper_note.md`
- Main thread synthesizes: theme clusters, shared limitations, research gaps, topic suggestions

**Output**: `refs/notes/{idx}_{paper}.md` + `refs/notes/digest.md`

---

### `deep-read`
Full-depth reading of a single paper.

- Reads entire PDF (abstract → appendix)
- Classifies paper type (causal empirical / descriptive / structural / theory)
- Fills structured `templates/deep_note.md` with 7 sections including Idea Seeds
- Enters interactive dialogue mode after writing the note

**Output**: `refs/notes/deep_{paper}.md`

---

### `paper-note`
Typeset a reading note as a clean LaTeX PDF for sharing with supervisors.

- Takes `deep_*.md` as input
- Uses minimal academic LaTeX template (`assets/template/main.tex`)
- Compiles with `scripts/build.sh`, previews with `scripts/preview.sh`

**Output**: `refs/notes/{slug}_note/build/main.pdf`

---

### `data-feasibility`
Assess data availability and acquisition strategy for a research idea.

- Matches variables to Chinese and international databases (`references/china_databases.md`)
- Evaluates scraping feasibility with legal risk ratings
- Suggests alternative variable construction (text, satellite, network)
- Produces structured feasibility verdict with acquisition roadmap

**Output**: `data/README.md`; summary appended to `refs/notes/digest.md`

---

### `topic-scout`
Socratic research topic selection dialogue.

- Loads context from `digest.md`, `deep_*.md`, `data/README.md` automatically
- Covers: novelty, identification credibility, data feasibility, scope/risk, journal fit
- One focused question per turn — never dumps all dimensions at once
- **Produces no written output until user explicitly confirms their choice**

**Output**: `refs/notes/topic_proposal.md`

---

### `minimal-beamer`
Build a LaTeX Beamer presentation from a bundled minimal template.

- Detects project context: reads `topic_proposal.md`, `digest.md`, `deep_*.md` if present
- Multi-round `AskUserQuestion` clarification before writing any frame
- Mandatory visual review after every build (`scripts/preview.sh`)

**Output**: `output/figures/slides_{name}.pdf` (inside project) or current directory

---

## Project Directory ↔ Skill Output Map

| Directory | Written by |
|-----------|-----------|
| `refs/*.pdf` | `ebsco-literature-pipeline` |
| `refs/manifest.csv` | `ebsco-literature-pipeline` |
| `refs/not_found.txt` | `ebsco-literature-pipeline` |
| `refs/notes/{idx}_*.md` | `lit-scout` |
| `refs/notes/digest.md` | `lit-scout` |
| `refs/notes/deep_*.md` | `deep-read` |
| `refs/notes/{slug}_note/` | `paper-note` |
| `refs/notes/topic_proposal.md` | `topic-scout` |
| `data/README.md` | `data-feasibility` (+ scaffold stub) |
| `output/figures/slides_*.pdf` | `minimal-beamer` |
| `paper/` | (user's own writing) |

---

## Prerequisites

| Skill | Requires |
|-------|---------|
| `ebsco-literature-pipeline` | Chrome DevTools MCP + CUFE WebVPN |
| `paper-note`, `minimal-beamer` | LaTeX (MacTeX / TeX Live) |
| `biz-research-scaffold` | bash (macOS/Linux) or pwsh (Windows) |
| All others | Claude Code only |
