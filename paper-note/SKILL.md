---
name: paper-note
description: Generate a beautifully typeset PDF reading note for a single academic paper using LaTeX. Takes the deep_note.md output from deep-read and compiles it into a clean, minimal academic document suitable for sharing with supervisors or colleagues. Use when the user wants to generate a PDF note from a paper reading, produce a formal reading note, share a paper summary with a supervisor, or says things like "生成论文笔记 PDF", "做一份可以发给导师的笔记", "把读书笔记编译成 PDF", "paper note PDF", "generate reading note".
---

# Paper Note

Typeset a reading note for a single academic paper into a minimal, clean LaTeX PDF.

## Input sources (in priority order)

1. `deep_note.md` from `deep-read` skill (preferred — already structured)
2. A PDF path — run `deep-read` first if note doesn't exist yet
3. User-provided text/notes directly

## Step 0: Check LaTeX Environment

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/check_env.sh
```

- Exit 0 → proceed
- Exit 1 → note missing packages, continue if pdflatex available
- Exit 2 → stop. Tell user to install:
  - macOS: `brew install --cask mactex` or `basictex`
  - Linux: `sudo apt install texlive-full latexmk`

## Step 1: Ask Two Questions

If not already clear from context, ask (one AskUserQuestion call):

1. **Your name** — for "Reading note by ___" on title block
2. **Chinese content?** — Yes → enable `xeCJK`; No → skip

Skip if both are clear from context.

## Step 2: Set Up Working Directory

```bash
NOTE_DIR="{project_refs}/notes/{paper_slug}_note"
cp -r ${CLAUDE_PLUGIN_ROOT}/assets/template/ "$NOTE_DIR/"
```

`paper_slug` = sanitized paper title (lowercase, underscores, no spaces).

## Step 3: Populate main.tex

Read `assets/template/main.tex`. Replace all `← replace` placeholders with actual content from the deep_note.md or PDF reading.

**Mapping from deep_note.md to LaTeX sections:**

| deep_note section | LaTeX section |
|-------------------|---------------|
| 一、核心论证 | \section{核心论证} |
| 二、研究设计 | \section{研究设计} |
| 三、数据 | \section{数据} |
| 四、核心结果 | \section{核心结果} |
| 五、批判性评估 | \section{批判性评估} |
| 六、Idea Seeds | \section{延伸方向} |
| 七、复现要点 | \section{复现要点} |

**Table content**: fill booktabs tables from the structured data in the note. Every table needs at least one data row.

**Rules**:
- No colored boxes, no `tcolorbox`, no `\begin{block}`
- Body text `\normalsize` throughout
- If a section has no content yet: write `\textit{待补充}` — never leave blank or omit the section
- Chinese text: uncomment `\usepackage{xeCJK}` in preamble if user said yes
- Math: use `amsmath` environments already loaded

## Step 4: Compile

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/build.sh "$NOTE_DIR/main.tex"
```

PDF lands at `$NOTE_DIR/build/main.pdf`.

Fix every error. Common issues:
- Chinese tofu (□□□) → `xeCJK` not loaded or wrong engine → switch to `xelatex`
- `booktabs` error → check table syntax
- Overfull hbox → shorten cell text or add `\small` inside table cells only

## Step 5: Visual Check

```bash
bash ${CLAUDE_PLUGIN_ROOT}/scripts/preview.sh "$NOTE_DIR/build/main.pdf"
```

Read preview images. Check:
- No text overflow
- Tables render correctly
- Section rule lines appear
- Header shows correct paper title + author
- Page numbers in footer
- No tofu characters

Fix issues, recompile.

## Step 6: Handoff

Tell user:
- PDF path: `$NOTE_DIR/build/main.pdf`
- Also copy to `{project_refs}/notes/{paper_slug}_note.pdf` for easy access

Then ask (AskUserQuestion):
- "Looks good, done"
- "Need edits — specify"

On edits: read the `.tex`, fix, recompile, preview, return to Step 6.

## Files

| File | Purpose |
|------|---------|
| `assets/template/main.tex` | Minimal academic LaTeX template |
| `scripts/build.sh` | Compile LaTeX |
| `scripts/check_env.sh` | Check LaTeX installation |
| `scripts/preview.sh` | Render PDF to PNG for visual check |
| `scripts/clean.sh` | Clean build artifacts |
