#!/usr/bin/env bash
# Usage: scaffold.sh <parent_dir> <project_name>
# Creates the research repo structure and git init.

set -euo pipefail

PARENT="${1:?Usage: scaffold.sh <parent_dir> <project_name>}"
NAME="${2:?Usage: scaffold.sh <parent_dir> <project_name>}"
BASE="$PARENT/$NAME"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -e "$BASE" ]]; then
  echo "ERROR: $BASE already exists" >&2
  exit 1
fi

mkdir -p "$BASE"/{data/raw,data/processed,code,output/tables,output/figures,output/logs,refs/notes,paper}
touch "$BASE"/data/README.md "$BASE"/code/README.md "$BASE"/paper/README.md

# .gitignore from template
cp "$SKILL_DIR/templates/gitignore.txt" "$BASE/.gitignore"

# root README
cat > "$BASE/README.md" << RDME
# $NAME

## Research Question


## Data
See data/README.md

## Workflow
code/   — analysis scripts (numbered 01_, 02_, ...)
output/ — tables, figures, logs
refs/   — PDF literature
paper/  — manuscript
RDME

# git init
if command -v git &>/dev/null; then
  cd "$BASE"
  git init -q
  git add .gitignore README.md data/README.md code/README.md paper/README.md
  git commit -q -m "chore: scaffold $NAME research repo"
  echo "git: initialized"
else
  echo "WARNING: git not found — skipped version control init"
fi

echo "DONE: $BASE"
find "$BASE" | sort | sed "s|$BASE||" | sed 's|^/||'
