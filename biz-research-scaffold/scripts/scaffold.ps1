# Usage: scaffold.ps1 -ParentDir <path> -ProjectName <name>
param(
  [Parameter(Mandatory)][string]$ParentDir,
  [Parameter(Mandatory)][string]$ProjectName
)

$ErrorActionPreference = "Stop"
$BASE = Join-Path $ParentDir $ProjectName
$SKILL_DIR = Split-Path (Split-Path $MyInvocation.MyCommand.Path)

if (Test-Path $BASE) {
  Write-Error "ERROR: $BASE already exists"; exit 1
}

@("data\raw","data\processed","code","output\tables","output\figures","output\logs","refs","refs\notes","paper") |
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
  git init -q
  git add .gitignore, README.md, data/README.md, code/README.md, paper/README.md
  git commit -q -m "chore: scaffold $ProjectName research repo"
  Write-Output "git: initialized"
} else {
  Write-Warning "git not found -- skipped version control init"
}

Write-Output "DONE: $BASE"
Get-ChildItem -Recurse $BASE | Select-Object -ExpandProperty FullName |
  ForEach-Object { $_.Replace($BASE, "").TrimStart("\") } | Sort-Object
