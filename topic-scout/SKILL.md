---
name: topic-scout
description: Socratic research topic selection dialogue. Helps the user evaluate and choose between multiple candidate research ideas through multi-round discussion covering novelty, identification credibility, data feasibility, and publication risk. Only produces a written report when the user explicitly confirms they have chosen a topic. Use when the user wants to think through which topic to pursue, compare research ideas, discuss whether an idea is worth doing, or says things like "帮我想想选题", "我有几个 idea 不知道选哪个", "这个选题值得做吗", "topic selection", "help me decide on a topic", "讨论一下选题".
---

# Topic Scout

Socratic dialogue for research topic selection. Multi-round discussion only. No report until user explicitly says they have decided.

## Core Rule

**Never produce a written report until the user says they have chosen.** Explicit signals only: "我选这个", "就做 Seed 2", "定了", "I've decided", "let's go with X". Anything ambiguous → keep discussing.

---

## Phase 0: Load Context

Before the first question, check if any of the following exist in the current project:

- `refs/{slug}/notes/digest.md` — lit-scout idea seeds (check `refs/notes/digest.md` as fallback)
- `refs/{slug}/notes/deep_*.md` — deep-read idea seeds
- `data/README.md` — data feasibility report

If found, read them silently. Use as background for the discussion. Tell the user: "I can see [N idea seeds / data feasibility notes] from your previous work. Want to start from those, or describe your ideas fresh?"

---

## Phase 1: Establish the Candidate Set

Ask the user to lay out their candidate ideas — however many, however rough.

For each idea, extract:
- Core RQ (one line)
- Proposed X / Y / identification sketch
- Why the user finds it interesting

---

## Phase 2: Socratic Discussion

Cover these dimensions one at a time, following the user's energy. Go deeper where they're uncertain, faster where they're confident.

**Novelty**
- What's the closest existing paper? What does this add?
- New fact / new mechanism / new method / new context?
- Would a referee at a top journal see this as meaningful?

**Identification**
- Source of exogenous variation?
- Most plausible threat? Can it be addressed?
- Similar identification used before? Did it work?

**Data**
- Reference `data-feasibility` output if available.
- If not: what data is needed, access status, bottleneck?

**Scope & Risk**
- PhD chapter vs. standalone paper?
- Worst-case scenario — what would kill this?
- Minimum viable version if full idea is too ambitious?

**Fit**
- Supervisor's interests / field match?
- Target journals? Are they open to this type?

### Dialogue rules

- One focused question per turn. Don't dump all dimensions at once.
- When user is stuck: offer 2-3 concrete options rather than open-ended questions.
- When user says something insightful: confirm and build on it.
- Push back gently on weak identification or vague novelty. Don't just validate.
- If one idea clearly dominates: say so directly.

---

## Phase 3: Report (Only When User Has Decided)

When user explicitly confirms their choice, write:

```markdown
# Research Topic Proposal

**Title (tentative)**: {working title}
**Date**: {today}

---

## Research Question

{One precise, answerable question}

## Motivation & Contribution

{2-3 sentences: why this matters, what gap it fills, how it goes beyond the closest papers}

## Empirical Strategy

**Y**: {definition + data source}
**X**: {definition + data source}
**Identification**: {exogenous variation + why credible}
**Method**: {DID / IV / RDD / etc.}

## Data

{Primary dataset(s), coverage, access status}

## Potential Concerns & Mitigants

| Concern | Mitigant |
|---------|---------|
| {threat 1} | {response} |
| {threat 2} | {response} |

## Target Journals

{2-3 journals, brief rationale}

## Next Steps

1. {immediate action}
2. {second step}
3. {third step}
```

Save to `{project}/refs/{slug}/notes/topic_proposal.md` if project exists. If `topic_proposal.md` already exists (from a previous topic-scout run), rename the old one to `topic_proposal_{YYYY-MM-DD}.md` before writing the new one — never overwrite previous proposals. If no project slug, save to current directory with the same archive logic.
