---
name: deep-read
description: Deep reading of a single academic paper to the level of full comprehension, replication, and idea generation. Reads the entire paper (not just abstract/intro/conclusion), produces a structured deep note covering research design, identification strategy, data, empirical specs, critical evaluation, and idea seeds. Ends in interactive dialogue mode for Q&A. Use when the user wants to deeply understand a specific paper, discuss a paper together, generate research ideas from a paper, or prepare for a paper presentation. Triggers on: "精读这篇文章", "帮我读这篇文章", "我想深入了解这篇论文", "deep read", "read this paper with me", "help me understand this paper", "generate ideas from this paper", or when user points to a specific PDF after running lit-scout.
---

# Deep Read

Full-depth reading of a single academic paper. Output: structured deep note + idea seeds + interactive dialogue.

## Input

Accept any of:
- PDF file path
- A note file from `lit-scout` (e.g. `refs/{slug}/notes/Hegde_2023.md`) — use as starting context, still read the PDF for full depth
- Just a paper title/DOI — check `refs/{project-slug}/pdfs/` first (ebsco convention), then `refs/`

Ask user (if not already clear):
- **Focus question**: "Is there a specific angle you want to explore? e.g. 'Can this be replicated with Chinese data?' or 'What are the weaknesses in the identification?' Leave blank for full coverage."

---

## Phase 1: Full Paper Reading

Read the **entire PDF** — every section, every table, every figure, every footnote that matters.

Reading order and focus:
1. **Abstract + Introduction** — understand the claim and why it matters
2. **Theory / Model section** — formal mechanism, testable predictions
3. **Data section** — construction of every key variable, sample restrictions
4. **Empirical strategy** — exact regression specs, FE structure, SE clustering
5. **Results** — every table and figure, what each coefficient means economically
6. **Robustness / Mechanism / Heterogeneity** — what threats were addressed, which weren't
7. **Conclusion** — what the authors think they proved, limitations they admit
8. **Appendix** — variable definitions, additional robustness, data construction details

Do NOT skim. If a section is dense, slow down.

---

## Phase 2: Write Deep Note

First, classify the paper type based on Phase 1 reading:
- **因果推断实证** — natural experiment, DID, IV, RDD, event study
- **描述性实证** — correlational, predictive, ML, measurement
- **结构估计** — structural model with estimation
- **理论模型** — analytical/theoretical, may have calibration
- **综述** — literature review, meta-analysis
- **其他** — mixed or doesn't fit above

Read `templates/deep_note.md` (next to this SKILL.md). Fill every field. For Section II (研究设计), only fill the subsections relevant to the paper type — write "不适用" for irrelevant subsections. Don't force a DID framing onto a theory paper.

Rules:
- Section VI (Idea Seeds): 3 seeds minimum. Each must be concrete — RQ, core variables, identification sketch, data requirement. Seeds come from: (a) explicit limitations, (b) untested mechanisms, (c) this setting applied to a different question, (d) user's focus question if given.
- Section V (批判性评估): be honest. If identification is weak, say so. Don't just echo authors' self-assessment.
- Keep technical terms in English, explanations in Chinese.

Save to: `{same folder as PDF}/notes/deep_{first_author}_{year}.md`

If a `lit-scout` note already exists for this paper (`notes/{first_author}_{year}.md`), append a line at the top: `**深度笔记**: [deep_{first_author}_{year}.md]` to cross-link.

---

## Phase 3: Summary to User

After writing the note, present a brief summary:

```
精读完成：{Title}

核心发现：{2句话}
识别策略：{1句话}
最大局限：{1句话}
Idea Seeds：{3个标题列出}

深度笔记已保存至：{path}
```

Then say: **"现在可以问我任何关于这篇文章的问题。"**

---

## Phase 4: Interactive Dialogue Mode

Stay in context. The user will ask questions. Answer based on what you read — not general knowledge.

Good question types to handle well:
- "这篇的识别策略有什么问题？" → 分析平行趋势、exclusion restriction、SUTVA
- "如果换成中国数据怎么做？" → 讨论数据可得性、制度差异、识别策略能否移植
- "Seed 2 的想法，你觉得可行吗？" → 深入讨论数据、识别、novelty
- "第 4 张表第 3 列的系数怎么理解？" → 解释经济意义和统计显著性
- "作者在 footnote 8 说了什么？" → 回答具体细节

If the user asks something not in the paper: say so explicitly. Don't hallucinate content.

Dialogue continues until user ends it or moves to next step (e.g. `ars-plan`).

When user says they want a PDF note to share with supervisor: hand off to `paper-note` skill, which takes the `deep_{pdf_basename}.md` output and compiles it to PDF.
