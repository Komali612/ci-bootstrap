#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# One-command setup for cicd-bootstrap. Safe to run more than once.
# It checks your tools, creates an isolated Python environment, installs the
# app, makes your .env file, and tells you if any keys are still missing.
# It does NOT touch a .env you already have.
#
#   Run it with:   bash setup.sh
# ---------------------------------------------------------------------------
set -euo pipefail
cd "$(dirname "$0")"

if [ -t 1 ]; then C=$'\033[1;36m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'; else C=""; G=""; Y=""; R=""; Z=""; fi
say(){ printf "\n%s%s%s\n" "$C" "$1" "$Z"; }
ok(){  printf "  %s✓%s %s\n" "$G" "$Z" "$1"; }
no(){  printf "  %s✗%s %s\n" "$R" "$Z" "$1"; }
tip(){ printf "  %s!%s %s\n" "$Y" "$Z" "$1"; }

say "1/5 · Checking the tools you need"
PY=""
for c in python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  no "Python 3.11+ not found."
  tip "Install it from https://www.python.org/downloads/  then run this again."
  exit 1
fi
ok "Python found — $($PY --version 2>&1)"
if command -v git >/dev/null 2>&1; then ok "git found"; else
  no "git not found."; tip "Install from https://git-scm.com/downloads  then run this again."; exit 1
fi
if command -v gh >/dev/null 2>&1; then ok "GitHub CLI (gh) found"; else
  tip "GitHub CLI not found (needed later to open pull requests)."
  tip "Install from https://cli.github.com  — you can keep going for now."
fi

say "2/5 · Creating an isolated Python environment (.venv)"
"$PY" -m venv .venv
./.venv/bin/python -m pip install --quiet --upgrade pip
ok "environment ready"

say "3/5 · Installing cicd-bootstrap and its dependencies"
./.venv/bin/python -m pip install --quiet -e .
ok "installed"

say "4/5 · Your keys file (.env)"
if [ -f .env ]; then
  ok ".env already exists — leaving it untouched"
else
  cp .env.example .env
  ok "created .env from the template"
  tip "Open .env and paste in your keys (see SETUP.md for how to get each)."
fi

say "5/5 · Checking your keys"
./.venv/bin/python - <<'PY'
import os
from cicd_bootstrap.config import load_dotenv, sonar_org, sonar_token
load_dotenv()
def show(name, val):
    mark = "set" if val else "MISSING  <-- add it to .env"
    print(f"  {'[ok]' if val else '[  ]'} {name:<18} {mark}")
show("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY"))
show("SONAR_TOKEN", sonar_token())
show("SONAR_ORG", sonar_org())
PY

say "Done. Next steps:"
cat <<'EOF'
  1. If any key shows MISSING above, open .env and paste it in.
        (SETUP.md explains exactly how to get each key.)
  2. Sign in to GitHub:     gh auth login
  3. Start the service:     ./.venv/bin/python -m cicd_bootstrap.cli --serve
  4. Open in your browser:  http://127.0.0.1:8000/
EOF
