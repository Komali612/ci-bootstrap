#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# add-harness-delegate.sh — install the Harness Docker delegate on THIS laptop.
#
# The delegate is Harness's on-machine worker — the twin of a GitHub self-hosted
# runner. It runs the CD deploy steps locally, so we mount the host Docker socket
# (/var/run/docker.sock) to let it run `docker` on your laptop. It's tagged
# `laptop` (like the runner label) and set to auto-restart, so it survives reboots
# better than the nohup'd GitHub runner.
#
# Before running:
#   1) Sign up at app.harness.io (free tier).
#   2) Create a delegate token + find your Account ID (see .env.example for where).
#   3) Put HARNESS_ACCOUNT_ID / HARNESS_DELEGATE_TOKEN / HARNESS_MANAGER_HOST in .env.
#   4) Make sure Docker Desktop is running.
#
#   bash scripts/add-harness-delegate.sh            # name defaults to laptop-delegate
#   bash scripts/add-harness-delegate.sh my-name
#
# NOTE: Harness shows you a ready-made `docker run` command when you create the
# delegate in its UI. This script mirrors that command using your .env values and
# adds the Docker-socket mount. If Harness's command differs for your account,
# we'll reconcile the two — treat this as the convenience wrapper.
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -t 1 ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; Z=$'\033[0m'; else G=""; Y=""; R=""; Z=""; fi
ok(){  printf "  %s✓%s %s\n" "$G" "$Z" "$1"; }
no(){  printf "  %s✗%s %s\n" "$R" "$Z" "$1" >&2; }
tip(){ printf "  %s!%s %s\n" "$Y" "$Z" "$1"; }

cd "$(dirname "$0")/.."
ENVF=".env"
val(){ { [ -f "$ENVF" ] && grep -E "^$1=" "$ENVF" | tail -1 | cut -d= -f2- | tr -d '"'"'"; } || true; }

ACCOUNT_ID="${HARNESS_ACCOUNT_ID:-$(val HARNESS_ACCOUNT_ID)}"
TOKEN="${HARNESS_DELEGATE_TOKEN:-$(val HARNESS_DELEGATE_TOKEN)}"
HOST="${HARNESS_MANAGER_HOST:-$(val HARNESS_MANAGER_HOST)}"
HOST="${HOST:-https://app.harness.io}"
NAME="${1:-laptop-delegate}"
# Pin a CURRENT delegate image. `harness/delegate:latest` is stale and hex-decodes
# the (base64) delegate token -> "Illegal hexadecimal character" crash. Override
# with HARNESS_DELEGATE_IMAGE if a newer tag exists on hub.docker.com/r/harness/delegate.
# The stock delegate has no docker CLI, and the deploy steps drive the host
# Docker via the mounted socket. Build a tiny image that bakes the client in
# (as root at build time), then run that. Override with HARNESS_DELEGATE_IMAGE.
BASE_IMG="harness/delegate:26.07.89703"
IMG="${HARNESS_DELEGATE_IMAGE:-cicd-bootstrap/harness-delegate:local}"
if [ -z "${HARNESS_DELEGATE_IMAGE:-}" ] && ! docker image inspect "$IMG" >/dev/null 2>&1; then
  echo "building delegate image with docker CLI ($IMG)…"
  docker build -q -t "$IMG" --build-arg BASE="$BASE_IMG" \
    -f "$(dirname "$0")/harness-delegate.Dockerfile" "$(dirname "$0")" >/dev/null
fi

if [ -z "$ACCOUNT_ID" ]; then no "HARNESS_ACCOUNT_ID is missing in .env"; exit 1; fi
if [ -z "$TOKEN" ]; then no "HARNESS_DELEGATE_TOKEN is missing in .env (create it in app.harness.io)"; exit 1; fi
if ! docker info >/dev/null 2>&1; then no "Docker isn't running — start Docker Desktop, then retry."; exit 1; fi

echo "Installing Harness delegate '$NAME' (tag: laptop) → $HOST"
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped \
  --cpus=1 --memory=2g \
  -e DELEGATE_NAME="$NAME" \
  -e NEXT_GEN="true" \
  -e DELEGATE_TYPE="DOCKER" \
  -e ACCOUNT_ID="$ACCOUNT_ID" \
  -e DELEGATE_TOKEN="$TOKEN" \
  -e DELEGATE_TAGS="laptop" \
  -e MANAGER_HOST_AND_PORT="$HOST" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "$IMG" >/dev/null
ok "delegate container started"
tip "it takes ~2-3 minutes to show 'connected' in Harness"
echo "  watch it connect:   docker logs -f $NAME"
echo "  verify in Harness:  Account Settings → Delegates  (look for '$NAME')"
