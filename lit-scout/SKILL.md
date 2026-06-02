---
name: lit-scout
description: Rapid literature digest for research topic selection. Reads a folder of PDF papers in parallel (one subagent per paper), each subagent writes its own structured note in Chinese. Main thread synthesizes research gaps and ideas across the full corpus. Use when the user wants to quickly understand a batch of papers, find research ideas, identify gaps, or needs a Chinese digest of downloaded papers. Triggers on: "帮我分析这批文献", "从这些 PDF 找研究 idea", "快速了解这些论文", "literature digest", "找研究空白", "选题", "research ideas from papers", or any request to process a folder of PDFs for research insight.
---

# Lit Scout

Parallel literature digest for rapid topic scouting.

```
{project}/refs/{slug}/pdfs/*.pdf  (named: {FirstAuthor}_{Year}_{Title}.pdf)
  -> Phase 1: N subagents (parallel, one per PDF)
              each reads abstract + intro + conclusion
              each writes notes/{first_author}_{year}.md using templates/paper_note.md
  -> Phase 2: main thread reads all .md files
              writes digest.md (synthesis — gaps, themes, ideas)
```

> **STOP — READ THIS FIRST**
>
> Phase 0 is NOT optional. You MUST use `AskUserQuestion` to ask the user about the research focus question before touching any PDFs. Do not auto-analyze, auto-detect, or assume. If you find yourself reading a PDF without having asked the focus question, you have made an error. Go back and ask.

## PDF Location Convention

**Lit-scout reads PDFs from `refs/{project-slug}/pdfs/`** — matching ebsco-literature-pipeline's output. If that directory doesn't exist, fall back to `refs/` root.

Notes are always written to `{pdf_dir}/../notes/` — i.e., `refs/{project-slug}/notes/`, alongside `pdfs/`. This keeps all per-project artifacts under one slug directory.

---

## Phase 0: Setup

**MANDATORY — DO NOT SKIP. This phase MUST complete before any PDF reading begins.**

### Step 0.1: Locate PDFs and load manifest

1. Find PDF folder: check `refs/*/pdfs/` (ebsco convention). If exactly one slug → use it. If multiple → ask user which project. Fallback: `refs/` root.
2. Load `manifest.csv` from `refs/{slug}/` — this contains `first_author`, `year`, `title`, `venue`, `subjects`, `has_pdf`.
3. List all `*.pdf` files. Report count.

### Step 0.2: Infer research directions from chat context + manifest

**DO NOT hardcode options.** Use TWO sources to infer 3–5 smart focus directions:

**Source 1 — Chat context (primary):**
- What has the user been discussing in this conversation? What research questions interest them?
- What project are they working on? What variables / mechanisms / policies do they care about?
- The user likely discussed their research agenda earlier in the chat — USE IT.

**Source 2 — Manifest (grounding):**
- Scan `title` and `subjects` columns in manifest.csv
- Identify recurring themes, keywords, clusters (e.g., patent/innovation/automation/labor/trade/climate)
- Cross-reference with chat context: which themes in the corpus align with the user's interests?

**Synthesize:** Produce 3–5 directions that:
1. Align with what the user cares about (from chat context)
2. Are actually covered by papers in the corpus (from manifest)
3. Each has: short label + 1-sentence description + rough paper count

If the chat context is empty or the user has not discussed research interests, fall back to manifest-only clustering:

```
scan titles + subjects → cluster by keyword frequency → top 3-5 clusters
```

If the corpus is too diverse to cluster meaningfully, say so and offer "全覆盖" as the default.

### Step 0.3: Ask user with AskUserQuestion (REQUIRED)

Use `AskUserQuestion` with these questions:

**Question 1 — Research focus** (single-select):
- The 3–5 dynamically-inferred directions from Step 0.2
- "全覆盖，不设焦点" — read all papers with standard template
- "自定义" — user types their own focus question (the "Other" option)

**Question 2 — Scope** (only ask if >30 PDFs, single-select):
- "全部处理" — process ALL papers
- "限制数量" — user specifies N (ask in follow-up or via "Other")

**Question 3 — PDF folder** (only ask if ambiguous，single-select):
- Confirm the detected slug or let user pick.

**Combine into ONE AskUserQuestion call** with 1–3 questions as needed.

If the user provides a custom focus question (via "Other"), use that directly. If they choose "全覆盖", no special angle — extract everything equally.

### Step 0.4: Create notes directory

`mkdir -p {pdf_dir}/../notes/`

**Checkpoint**: You MUST have the user's answers to ALL questions before entering Phase 1. If you find yourself reading a PDF without having asked, STOP — you made an error.

---

## Phase 1: Parallel Paper Notes

Spawn one subagent per PDF, all at once in parallel.

Each subagent:
1. Reads `templates/paper_note.md` (next to this SKILL.md)
2. Reads the PDF — focus on abstract, introduction (first 3-4 pages), conclusion (last 2 pages) only
3. Fills in every field of the template. If a field cannot be determined: write `不明确`
4. Writes the completed note to `{folder}/notes/{first_author}_{year}.md` (create `notes/` if not exists)
5. If PDF is unreadable (corrupted/scanned/password): writes a minimal note with `**[无法读取]**` and skips all fields

Metadata from `manifest.csv` (if available) pre-fills title/author/year/venue — subagent should use it.
PDF filenames are meaningful: `{FirstAuthor}_{Year}_{Title}.pdf` — no need for index numbers.

The focus question (if given) informs which aspects to emphasize in "故事逻辑" and "未回答的问题".

---

## Phase 2: Synthesis Digest

After ALL subagents complete, main thread reads every `*.md` note file from `{folder}/notes/`.

**Before writing**: Check if `{project}/refs/{slug}/notes/digest.md` already exists (from prior data-feasibility or lit-scout runs). If it exists, read it and preserve the existing sections. Lit-scout's synthesis is appended at the bottom under a dated header: `## Lit-scout 更新 ({date})`. Never delete existing content.

Write (or append to) `{project}/refs/{slug}/notes/digest.md`:

```markdown
# Literature Digest
**生成时间**: {date}
**文献数量**: {N} 篇（成功读取 {M} 篇，{N-M} 篇无法读取）
**来源目录**: {folder}
**研究焦点**: {focus question or "全覆盖"}

---

## 快速索引

| 作者(年) | 期刊 | Y | X | 方法 |
|---------|------|---|---|------|
| Author (Year) | ... | ... | ... | ... |
...

---

## 主题聚类

{将这批文献按研究主题分组，3-5个主题，每个主题列相关论文（作者+年份）和一句话说明共同点}

---

## 已有研究的共同局限

{这批文献集体存在哪些盲点？数据限制？外部效度？机制未打开？仅限某国/某期？}

---

## 研究空白

{3-5个具体空白，每条：
- **空白**: 什么问题没人回答？
- **为什么没人做**: 数据难、识别难、还是太新？
- **相关文献**: Author (Year)}

---

## 选题建议

{2-3个具体可操作的选题，每条：
- **研究问题**: 一句话
- **Y / X / 识别策略**
- **Novelty**: 比已有文献多贡献了什么
- **参考基础**: Author (Year)}
```

---

## File Structure After Completion

```
refs/{project-slug}/
├── papers.json                  (from ebsco search)
├── manifest.csv                 (from ebsco search)
├── pdfs/                        (from ebsco download)
│   ├── Hegde_2023_Patent_Publication_and_Innovation.pdf
│   ├── Babina_2023_Cutting_the_Innovation_Engine.pdf
│   └── downloaded.json
├── search/                      (raw search results)
├── supplement/                  (supplementary queries)
└── notes/                       (lit-scout output)
    ├── Hegde_2023.md
    ├── Babina_2023.md
    └── digest.md                (synthesis — main output for user)
```


