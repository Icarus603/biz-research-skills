---
name: lit-scout
description: Rapid literature digest for research topic selection. Reads a folder of PDF papers in parallel (one subagent per paper), each subagent writes its own structured note in Chinese. Main thread synthesizes research gaps and ideas across the full corpus. Use when the user wants to quickly understand a batch of papers, find research ideas, identify gaps, or needs a Chinese digest of downloaded papers. Triggers on: "帮我分析这批文献", "从这些 PDF 找研究 idea", "快速了解这些论文", "literature digest", "找研究空白", "选题", "research ideas from papers", or any request to process a folder of PDFs for research insight.
---

# Lit Scout

Parallel literature digest for rapid topic scouting.

```
refs/*.pdf
  → Phase 1: N subagents (parallel, one per PDF)
              each reads abstract + intro + conclusion
              each writes {idx}_{name}.md using templates/paper_note.md
  → Phase 2: main thread reads all .md files
              writes digest.md (synthesis only — gaps, themes, ideas)
```

---

## Phase 0: Setup

Ask user (combine into one message if multiple unknowns):
- **PDF folder** — default: `refs/` in current working directory
- **Focus question** (optional) — specific angle, e.g. "AI and labor market". Leave blank = extract everything.

Load `manifest.csv` if present in the folder — use for author/year/venue without reading PDFs.

List all `*.pdf` files. Report count. If > 30, warn: "Found N papers — will spawn N subagents in parallel. Continue?"

---

## Phase 1: Parallel Paper Notes

Spawn one subagent per PDF, all at once in parallel.

Each subagent:
1. Reads `templates/paper_note.md` (next to this SKILL.md)
2. Reads the PDF — focus on abstract, introduction (first 3-4 pages), conclusion (last 2 pages) only
3. Fills in every field of the template. If a field cannot be determined: write `不明确`
4. Writes the completed note to `{folder}/notes/{idx:03d}_{pdf_basename}.md` (create `notes/` if not exists)
5. If PDF is unreadable (corrupted/scanned/password): writes a minimal note with `**[无法读取]**` and skips all fields

Metadata from `manifest.csv` (if available) pre-fills title/author/year/venue — subagent should use it.

The focus question (if given) informs which aspects to emphasize in "故事逻辑" and "未回答的问题".

---

## Phase 2: Synthesis Digest

After ALL subagents complete, main thread reads every `*.md` note file from `{folder}/notes/`.

Write `{folder}/notes/digest.md`:

```markdown
# Literature Digest
**生成时间**: {date}
**文献数量**: {N} 篇（成功读取 {M} 篇，{N-M} 篇无法读取）
**来源目录**: {folder}
**研究焦点**: {focus question or "全覆盖"}

---

## 快速索引

| # | 作者(年) | 期刊 | Y | X | 方法 |
|---|---------|------|---|---|------|
| 001 | ... | ... | ... | ... | ... |
...

---

## 主题聚类

{将这批文献按研究主题分组，3-5个主题，每个主题列相关论文编号和一句话说明共同点}

---

## 已有研究的共同局限

{这批文献集体存在哪些盲点？数据限制？外部效度？机制未打开？仅限某国/某期？}

---

## 研究空白

{3-5个具体空白，每条：
- **空白**: 什么问题没人回答？
- **为什么没人做**: 数据难、识别难、还是太新？
- **相关文献**: [编号]}

---

## 选题建议

{2-3个具体可操作的选题，每条：
- **研究问题**: 一句话
- **Y / X / 识别策略**
- **Novelty**: 比已有文献多贡献了什么
- **参考基础**: [编号]}
```

---

## File Structure After Completion

```
{project}/refs/
├── 001.pdf
├── 002.pdf
├── ...
├── manifest.csv
└── notes/
    ├── 001_paper_a.md
    ├── 002_paper_b.md
    ├── ...
    └── digest.md       (synthesis — main output for user)
```


