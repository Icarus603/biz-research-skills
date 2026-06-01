# Biz Research Skills for Claude Code

[![Version](https://img.shields.io/badge/version-v1.0.0-blue)](https://github.com/Icarus603/biz-research-skills/releases/tag/v1.0.0)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A suite of Claude Code skills for academic research in business and social science — economics, finance, accounting, management, marketing. Covers the full workflow from project setup to literature review to topic selection to presentation.

**Install in 30 seconds** (Claude Code CLI / VS Code / JetBrains):

```text
/plugin marketplace add Icarus603/biz-research-skills
/plugin install biz-research-skills
```

Then say "帮我新建一个研究项目" or "find papers on AI and labor markets" and the right skill triggers automatically.

---

## What this does

Eight skills that work together as a single research workflow:

```
biz-research-scaffold          →  set up project repo (cross-platform)
       ↓
ebsco-literature-pipeline      →  discover papers via S2 + OpenAlex + Crossref + WebSearch
                                   download PDFs via CUFE WebVPN (EBSCO) + open access
       ↓
lit-scout                      →  parallel digest: one subagent per PDF → notes + synthesis
       ↓
deep-read                      →  full paper reading + idea seeds + dialogue mode
       ↓
paper-note                     →  typeset reading note as LaTeX PDF (for supervisor)
       ↓
data-feasibility               →  assess data availability: China DBs + scraping options
       ↓
topic-scout                    →  Socratic topic selection → topic_proposal.md
       ↓
minimal-beamer                 →  LaTeX Beamer slides (reads project context automatically)
```

---

## Quick install

**Prerequisites**

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code/setup) (latest)
- `ANTHROPIC_API_KEY` set
- *For `ebsco-literature-pipeline`*: Chrome with remote debugging port open + CUFE WebVPN credentials
  ```bash
  # One-time setup
  echo 'CUFE_USERNAME=学号' > ~/.cufe_credentials
  echo 'CUFE_PASSWORD=密码' >> ~/.cufe_credentials
  chmod 600 ~/.cufe_credentials
  open -a "Google Chrome" --args --remote-debugging-port=9222
  ```
- *For `paper-note` and `minimal-beamer`*: LaTeX installation
  - macOS: `brew install --cask mactex` or `basictex`
  - Linux: `sudo apt install texlive-full latexmk`

**Plugin install (recommended):**

```text
/plugin marketplace add Icarus603/biz-research-skills
/plugin install biz-research-skills
```

**Manual install (symlink):**

```bash
git clone git@github.com:Icarus603/biz-research-skills.git ~/code/dev/biz-research-skills
cd ~/.claude/skills
for skill in biz-research-scaffold data-feasibility deep-read ebsco-literature-pipeline lit-scout minimal-beamer paper-note topic-scout; do
  ln -s ~/code/dev/biz-research-skills/$skill $skill
done
```

---

## Skills

### `biz-research-scaffold`
Creates a standardized research project directory. Detects your OS (bash / PowerShell) and installed tools (Stata, R, Python, git). Asks only what it doesn't know.

```
project/
├── data/raw/  processed/  README.md
├── code/
├── output/tables/  figures/  logs/
├── refs/  notes/          ← where all the skills below write their output
├── paper/
├── .gitignore
└── README.md
```

---

### `ebsco-literature-pipeline`
Literature discovery and bulk PDF download via EBSCO Search API.

- **Discovery**: EBSCO API via Chrome CDP — SO/DT field-code queries, journal-scoped, paginated
- **Auto-login**: reads `~/.cufe_credentials`, fills CUFE CAS SSO form, persists session cookies
- **Download**: parallel `Promise.all` fetch + `<a download>` with semantic names (`{Author}_{Year}_{Title}.pdf`)
- **Journal scope**: All journals / Economics Top-5 / UTD24 / FT50
- **Output**: `refs/*.pdf` (named) + `refs/papers.json` + `refs/manifest.csv`
- **CLI**: `python3 scripts/ebsco_pipeline.py search|download`

> Requires Chrome `--remote-debugging-port=9222` and CUFE credentials in `~/.cufe_credentials`.

---

### `lit-scout`
Reads all PDFs in `refs/` in parallel — one subagent per paper. Each subagent writes a structured Chinese-language note. The main thread synthesizes themes, gaps, and topic suggestions.

- Reads: abstract + intro + conclusion only (fast)
- Each note follows `templates/paper_note.md`
- **Output**: `refs/notes/{first_author}_{year}.md` per paper + `refs/notes/digest.md`

---

### `deep-read`
Full read of a single paper — every section, every table, every appendix. Classifies paper type (causal empirical / structural / theory / descriptive) and fills accordingly.

- Generates 3+ concrete **Idea Seeds** (RQ, Y, X, identification sketch, data requirement)
- Enters **interactive dialogue mode** after writing the note — ask anything about the paper
- **Output**: `refs/notes/deep_{paper}.md`

---

### `paper-note`
Compiles a `deep_*.md` reading note into a clean, minimal LaTeX PDF for sharing with supervisors.

- Template: A4, `lmodern`, `booktabs` tables, section rules, header with paper title/author
- Compiles with `scripts/build.sh`, previews page-by-page before delivering
- **Output**: `refs/notes/{slug}_note/build/main.pdf`

---

### `data-feasibility`
Assesses data availability for a research idea. Covers Chinese commercial databases (CSMAR, WIND, CNRDS, CFPS, CHFS...), international databases, and public scraping sources.

- Matches each variable (Y, X, IV, controls) to available sources
- Evaluates scraping feasibility with legal risk ratings (Low / Medium / High)
- Suggests alternative construction (NLP, satellite, network data)
- **Output**: structured report → `data/README.md`

---

### `topic-scout`
Socratic dialogue for choosing between candidate research ideas. Covers novelty, identification credibility, data feasibility, scope/risk, and journal fit. One question per turn.

- Automatically loads `digest.md`, `deep_*.md`, `data/README.md` as context
- **Never writes output until you explicitly say you've decided**
- **Output**: `refs/notes/topic_proposal.md`

---

### `minimal-beamer`
Builds a LaTeX Beamer presentation from a bundled minimal template. Detects project context — reads `topic_proposal.md` and `deep_*.md` automatically to pre-fill content.

- Multi-round `AskUserQuestion` clarification before writing any frame
- Mandatory visual review after every build
- **Output**: `output/figures/slides_{name}.pdf`

---

## Project directory ↔ skill output

| Path | Written by |
|------|-----------|
| `refs/*.pdf` | `ebsco-literature-pipeline` (named: `{Author}_{Year}_{Title}.pdf`) |
| `refs/papers.json` | `ebsco-literature-pipeline` |
| `refs/manifest.csv` | `ebsco-literature-pipeline` |
| `refs/notes/{first_author}_{year}.md` | `lit-scout` |
| `refs/notes/digest.md` | `lit-scout` |
| `refs/notes/deep_*.md` | `deep-read` |
| `refs/notes/{slug}_note/` | `paper-note` |
| `refs/notes/topic_proposal.md` | `topic-scout` |
| `data/README.md` | `data-feasibility` |
| `output/figures/slides_*.pdf` | `minimal-beamer` |

---

## Workflow example

```
# 1. Set up project
"帮我新建一个关于 AI 对劳动力市场影响的研究项目"
→ biz-research-scaffold creates ~/research/ai_labor_market/

# 2. Find and download papers
"找一下 AER/QJE/JPE 里关于 AI 和劳动力市场的文献"
→ ebsco-literature-pipeline: discovers 40 papers, downloads PDFs to refs/

# 3. Quick digest
"帮我快速读一遍这批文献"
→ lit-scout: 40 subagents in parallel → 40 notes + digest.md with 5 idea seeds

# 4. Deep read a paper
"精读一下 Acemoglu 2022 那篇"
→ deep-read: full read → deep_acemoglu_2022.md + dialogue mode

# 5. Check data availability
"这个 idea 的数据怎么找？"
→ data-feasibility: CSMAR + CNRDS patent data → feasibility report

# 6. Choose a topic
"帮我想想选哪个选题"
→ topic-scout: Socratic dialogue → topic_proposal.md

# 7. Make slides
"做一个汇报用的 slides"
→ minimal-beamer: reads topic_proposal.md → LaTeX Beamer PDF
```
