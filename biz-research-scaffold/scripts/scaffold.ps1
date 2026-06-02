# Usage: scaffold.ps1 -ParentDir <path> -ProjectName <name>
# Creates the research repo structure and git init.
# Tolerates target dir if it exists but is empty (or only has .git).

param(
  [Parameter(Mandatory)][string]$ParentDir,
  [Parameter(Mandatory)][string]$ProjectName
)

$ErrorActionPreference = "Stop"
$BASE = Join-Path $ParentDir $ProjectName
$SKILL_DIR = Split-Path (Split-Path $MyInvocation.MyCommand.Path)

if (Test-Path $BASE) {
  $contentCount = (Get-ChildItem -Path $BASE -Force -Name |
    Where-Object { $_ -ne '.git' }).Count
  if ($contentCount -gt 0) {
    Write-Error "ERROR: $BASE exists and is not empty ($contentCount entries)"; exit 1
  }
  Write-Output "NOTICE: $BASE exists but is empty -- scaffolding in-place"
}

# refs created empty -- literature skills create per-project slug subdirs
# (refs\{slug}\pdfs, refs\{slug}\notes, ...) on demand. No flat refs\notes.
@("data\raw","data\processed","code","output\tables","output\figures","output\logs","refs","paper") |
  ForEach-Object { New-Item -ItemType Directory -Force -Path "$BASE\$_" | Out-Null }

"" | Set-Content "$BASE\data\README.md"
"" | Set-Content "$BASE\code\README.md"
"" | Set-Content "$BASE\paper\README.md"

# .gitignore from template
Copy-Item "$SKILL_DIR\templates\gitignore.txt" "$BASE\.gitignore"

# root README
@"
# $ProjectName

## Research Question


## Data
See data/README.md

## Workflow
code/   -- analysis scripts (numbered 01_, 02_, ...)
output/ -- tables, figures, logs
refs/   -- PDF literature
paper/  -- manuscript
"@ | Set-Content "$BASE\README.md"

# git init
if (Get-Command git -ErrorAction SilentlyContinue) {
  Set-Location $BASE
  if (Test-Path .git) {
    Write-Output "git: already initialized -- skipping"
  } else {
    git init -q
    git add .gitignore, README.md, data/README.md, code/README.md, paper/README.md
    git commit -q -m "chore: scaffold $ProjectName research repo"
    Write-Output "git: initialized"
  }
} else {
  Write-Warning "git not found -- skipped version control init"
}

Write-Output "DONE: $BASE"
Get-ChildItem -Recurse $BASE | Select-Object -ExpandProperty FullName |
  ForEach-Object { $_.Replace($BASE, "").TrimStart("\") } | Sort-Object
