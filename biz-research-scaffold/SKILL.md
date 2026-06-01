---
name: biz-research-scaffold
description: Scaffold a new academic research repository for business/social science fields (economics, finance, accounting, management, marketing, etc.). Use when the user wants to start a new research project, create a paper repo, set up a research directory structure, or says things like "scaffold a research repo", "start a new paper on X", "new research project", "set up a project for X". Detects OS and installed tools first. Asks only what is unclear, then runs the scaffold script.
---

# Biz Research Scaffold

## Phase 0: Detect OS

```bash
uname -s 2>/dev/null || echo "WINDOWS"
```

- `Darwin` / `Linux` → bash → use `scripts/scaffold.sh`
- `WINDOWS` / error → pwsh → use `scripts/scaffold.ps1`

## Phase 1: Detect Tools

**bash:**
```bash
for tool in stata R uv python3 git; do
  which $tool 2>/dev/null && echo "$tool:yes" || echo "$tool:no"
done
```

**pwsh:**
```powershell
foreach ($tool in @("stata","R","uv","python","git")) {
  if (Get-Command $tool -ErrorAction SilentlyContinue) { "$tool`:yes" } else { "$tool`:no" }
}
```

Analysis tools: stata, R, uv/python3. Infrastructure: git.

## Phase 2: Decide What to Ask (AskUserQuestion)

Evaluate independently — only ask what is genuinely unclear:

| Question | Skip if | Ask if |
|----------|---------|--------|
| Project name | stated in message | not given |
| Primary tool | exactly 1 analysis tool detected → auto-select | 0 detected, or 2+ detected |
| Paper language | inferable from context | ambiguous |

Git: never ask. Script handles it automatically (init if found, warns if not).

**If 0 tools detected**, list all options with install instructions:
- Stata: stata.com/download
- R: `brew install r` (mac) / `winget install RProject.R` (win)
- Python/uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` (mac/linux) / `irm https://astral.sh/uv/install.ps1 | iex` (win pwsh)

Combine all remaining questions into ONE AskUserQuestion call. If nothing unclear, skip entirely.

## Phase 3: Confirm Location

Ask (plain text): "Where should this be created? (default: current directory)"
Skip if user already gave a path.

## Phase 4: Run Scaffold Script

Locate the script next to this SKILL.md file.

**bash (macOS/Linux):**
```bash
bash "<skill_dir>/scripts/scaffold.sh" "<parent_dir>" "<project_name>"
```

**pwsh (Windows):**
```powershell
pwsh "<skill_dir>\scripts\scaffold.ps1" -ParentDir "<parent_dir>" -ProjectName "<project_name>"
```

The script creates all directories, writes `.gitignore` from `templates/gitignore.txt`, writes a root `README.md`, and runs `git init` if git is available. It prints the created tree when done.

## Phase 5: Final Message

After script completes, tell the user:

- If their chosen tool was not detected: "Warning: {tool} not found. Install before running analysis."
- Always: "To download papers into this project, use `ebsco-literature-pipeline` with target dir: `{full_path}/refs/`"
