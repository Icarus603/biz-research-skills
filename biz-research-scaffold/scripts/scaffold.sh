#!/usr/bin/env bash
# Usage: scaffold.sh <parent_dir> <project_name>
# Creates the research repo structure and git init.
# Tolerates target dir if it exists but is empty (or only has .git).

set -euo pipefail

PARENT="${1:?Usage: scaffold.sh <parent_dir> <project_name>}"
NAME="${2:?Usage: scaffold.sh <parent_dir> <project_name>}"
BASE="$PARENT/$NAME"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -e "$BASE" ]]; then
  # Count non-hidden, non-.git entries
  content_count=$(find "$BASE" -mindepth 1 -maxdepth 1 ! -name '.git' 2>/dev/null | wc -l | tr -d ' ')
  if [[ "$content_count" -gt 0 ]]; then
    echo "ERROR: $BASE exists and is not empty ($content_count entries)" >&2
    exit 1
  fi
  echo "NOTICE: $BASE exists but is empty — scaffolding in-place"
fi

# refs/ created empty — literature skills create per-project slug subdirs
# (refs/{slug}/pdfs, refs/{slug}/notes, refs/{slug}/web, ...) on demand.
# Do NOT pre-create a flat refs/notes — contradicts the refs/{slug}/ convention.
mkdir -p "$BASE"/{data/raw,data/processed,code,output/tables,output/figures,output/logs,refs,paper}
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
  if [[ -d .git ]]; then
    echo "git: already initialized — skipping"
  else
    git init -q
    git add .gitignore README.md data/README.md code/README.md paper/README.md
    git commit -q -m "chore: scaffold $NAME research repo"
    echo "git: initialized"
  fi
else
  echo "WARNING: git not found — skipped version control init"
fi

echo "DONE: $BASE"
find "$BASE" | sort | sed "s|$BASE||" | sed 's|^/||'
