#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# add-runner.sh — attach a self-hosted deploy runner to ONE GitHub repo.
#
# The CD pipeline deploys to THIS laptop, which only works if a self-hosted
# runner labelled "laptop" is attached to the repo being deployed. On a
# personal GitHub account a runner belongs to a single repo, so run this once
# per repo you want to deploy. Safe to re-run (it replaces the old one).
#
#   bash scripts/add-runner.sh https://github.com/OWNER/REPO
#   bash scripts/add-runner.sh OWNER/REPO
#
# Needs: the GitHub CLI (gh) signed in with `gh auth login`, and curl.
# Leaves the runner listening in the background. It stops if you log out or
# reboot — just re-run this script (or `cd ~/actions-runner-REPO && ./run.sh`)
# to bring it back.
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -t 1 ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'; else G=""; Y=""; R=""; Z=""; fi
ok(){  printf "  %s✓%s %s\n" "$G" "$Z" "$1"; }
no(){  printf "  %s✗%s %s\n" "$R" "$Z" "$1" >&2; }
tip(){ printf "  %s!%s %s\n" "$Y" "$Z" "$1"; }

REPO_INPUT="${1:-}"
if [ -z "$REPO_INPUT" ]; then
  no "Tell me which repo. Example:"
  echo "     bash scripts/add-runner.sh https://github.com/OWNER/REPO"
  exit 1
fi

# --- normalise the input to  owner/name  -----------------------------------
slug="$REPO_INPUT"
slug="${slug#https://github.com/}"
slug="${slug#http://github.com/}"
slug="${slug%.git}"
slug="${slug%/}"
owner="${slug%%/*}"
name="${slug##*/}"
if [ -z "$owner" ] || [ -z "$name" ] || [ "$owner" = "$slug" ]; then
  no "Couldn't read an OWNER/REPO from: $REPO_INPUT"
  tip "Use the repo's URL, e.g. https://github.com/Komali612/my-service"
  exit 1
fi
echo "Repo: $owner/$name"

# --- prerequisites ---------------------------------------------------------
# gh may be installed but missing from this shell's PATH (common with conda's
# 'base' environment), so also look in the usual Homebrew/system locations.
GH=""
for cand in "$(command -v gh 2>/dev/null || true)" /opt/homebrew/bin/gh /usr/local/bin/gh /usr/bin/gh "$HOME/.local/bin/gh"; do
  if [ -n "$cand" ] && [ -x "$cand" ]; then GH="$cand"; break; fi
done
if [ -z "$GH" ]; then
  no "GitHub CLI (gh) not found. Install from https://cli.github.com then run: gh auth login"
  exit 1
fi
if ! "$GH" auth status >/dev/null 2>&1; then
  no "You're not signed in to GitHub. Run:  $GH auth login   then try again."
  exit 1
fi
if ! command -v curl >/dev/null 2>&1; then
  no "curl not found (it ships with macOS — check your PATH)."
  exit 1
fi

# --- pick the right runner build for this machine --------------------------
case "$(uname -s)" in
  Darwin) os="osx" ;;
  Linux)  os="linux" ;;
  *) no "This script supports macOS and Linux only."; exit 1 ;;
esac
case "$(uname -m)" in
  arm64|aarch64) arch="arm64" ;;
  x86_64|amd64)  arch="x64" ;;
  *) no "Unsupported CPU: $(uname -m)"; exit 1 ;;
esac

DIR="$HOME/actions-runner-$name"

# --- download the runner software once (skip if already there) -------------
if [ ! -x "$DIR/run.sh" ]; then
  echo "Downloading the GitHub Actions runner (one-time)…"
  ver="$("$GH" api repos/actions/runner/releases/latest --jq .tag_name | sed 's/^v//')"
  file="actions-runner-${os}-${arch}-${ver}.tar.gz"
  mkdir -p "$DIR"
  curl -fSL --retry 3 -o "$DIR/$file" \
    "https://github.com/actions/runner/releases/download/v${ver}/${file}"
  tar xzf "$DIR/$file" -C "$DIR"
  rm -f "$DIR/$file"
  ok "runner v$ver installed at $DIR"
else
  ok "runner already installed at $DIR — reusing it"
fi

# --- register it to this repo (label: laptop) ------------------------------
echo "Registering the runner with $owner/$name…"
reg_token="$("$GH" api -X POST "repos/$owner/$name/actions/runners/registration-token" --jq .token)"
(
  cd "$DIR"
  ./config.sh \
    --url "https://github.com/$owner/$name" \
    --token "$reg_token" \
    --name "laptop-$name" \
    --labels laptop \
    --work _work \
    --unattended --replace >/dev/null
)
ok "registered as 'laptop-$name' with labels: self-hosted, laptop"

# --- start it in the background --------------------------------------------
echo "Starting the runner…"
( cd "$DIR" && nohup ./run.sh >"$DIR/runner.log" 2>&1 & )
sleep 5

status="$("$GH" api "repos/$owner/$name/actions/runners" \
  --jq '.runners[] | select(.name=="laptop-'"$name"'") | .status' 2>/dev/null || true)"
if [ "$status" = "online" ]; then
  ok "runner is ONLINE — deploys to $owner/$name will now run on this laptop"
else
  tip "runner registered but status is '${status:-unknown}'. Check $DIR/runner.log"
fi

echo
echo "Done. You can now deploy $owner/$name from the CI+CD agent (:8001) or CD agent (:8002)."
