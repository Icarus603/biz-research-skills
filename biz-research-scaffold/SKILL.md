---
name: biz-research-scaffold
description: Scaffold a new academic research repository for business/social science fields (economics, finance, accounting, management, marketing, etc.). Use when the user wants to start a new research project, create a paper repo, set up a research directory structure, or says things like "scaffold a research repo", "start a new paper on X", "new research project", "set up a project for X". Detects OS and installed tools first. Asks only what is unclear, then runs the scaffold script.
---

# Biz Research Scaffold

## Phase 0: Context Sniffing

Understand where we are BEFORE asking questions.

```bash
echo "CWD=$(pwd)"
echo "CWD_NAME=$(basename "$(pwd)")"
ls -1a "$(pwd)" | head -20
```

Decision table:

| CWD state | Action |
|-----------|--------|
| Empty (no files, or only `.git`) + dirname NOT generic (not `~`, `Desktop`, `code`, `research`) | **Infer** project name = dirname. Location = CWD. Skip project name + location questions. |
| Empty + dirname generic | Ask project name. Location = CWD. Skip location question. |
| Has scaffold dirs (`data/`, `code/`, `paper/`, `refs/`) | **Warn**: already scaffolded. Ask user if re-scaffold wanted. If yes, ask for new name/path. |
| Non-empty, non-scaffold | **Warn**: CWD not empty, not a recognized project. Ask if still want to scaffold here. |

Generic dirname list: `~`, `home`, `Desktop`, `Documents`, `code`, `dev`, `projects`, `research`, `work`, `src`, `root`, `tmp`, `Downloads`.

## Phase 1: Detect OS + Tools (merged)

```bash
uname -s 2>/dev/null || echo "WINDOWS"
for tool in stata R uv python3 git; do
  which $tool 2>/dev/null && echo "$tool:yes" || echo "$tool:no"
done
```

| OS | Script |
|----|--------|
| `Darwin` / `Linux` | `scripts/scaffold.sh` |
| `WINDOWS` / error | `scripts/scaffold.ps1` |

Analysis tools: stata, R, uv/python3. Infrastructure: git.

## Phase 2: Decide What to Ask

Only ask what Phase 0 didn't resolve:

| Question | Skip if | Ask if |
|----------|---------|--------|
| Project name | Inferred from CWD dirname, or stated in user message | Dirname generic, or user didn't state |
| Primary tool | Exactly 1 analysis tool detected → auto-select | 0 detected, or 2+ detected |
| Paper language | Stated in user message | Always ask — user choice, not inferrable from path/system locale |
| Location | CWD empty + inferred name, or user gave path | Ambiguous — CWD non-empty, or user unclear |

**If 0 tools detected**, list all options with install instructions:
- Stata: stata.com/download
- R: `brew install r` (mac) / `winget install RProject.R` (win)
- Python/uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (mac/linux) / `irm https://astral.sh/uv/install.ps1 | iex` (win pwsh)

Combine all remaining questions into ONE AskUserQuestion call. If nothing unclear, skip Phase 2 entirely → go straight to Phase 3.

## Phase 3: Run Scaffold Script

Script path: `<skill_dir>/scripts/scaffold.sh` (or `.ps1` for Windows).

When CWD IS the target (empty dir, inferred name):
```bash
bash "<skill_dir>/scripts/scaffold.sh" "$(dirname "$CWD")" "$(basename "$CWD")"
```

When CWD is parent, new subdir needed:
```bash
bash "<skill_dir>/scripts/scaffold.sh" "$CWD" "<project_name>"
```

When user specified custom path:
```bash
bash "<skill_dir>/scripts/scaffold.sh" "<parent_dir>" "<project_name>"
```

The script creates all directories, writes `.gitignore` from `templates/gitignore.txt`, writes a root `README.md`, and runs `git init` if git is available. It tolerates an existing empty target directory.

## Phase 4: Final Message

After script completes:

- If chosen tool not detected: "Warning: {tool} not found. Install before running analysis."
- Always: "To download papers into this project, use `ebsco-literature-pipeline` with target dir: `{full_path}/refs/`"
- Always: "PDFs under `refs/*/pdfs/` are gitignored by default (large binaries). Metadata files (papers.json, manifest.csv, downloaded.json) are tracked."
- If paper language is Chinese: "论文语言：中文。README 和初始文件使用英文标题（学术惯例），如需中文内容请自行编辑。"
