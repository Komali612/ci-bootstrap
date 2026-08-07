"""Generate a CD (deploy) workflow -- the delivery half of the pipeline.

CI ends by pushing an image to GHCR (``ghcr.io/<owner>/<name>:<sha>``); CD picks
that image up and *runs* it. This module is the deterministic generator for the
deploy workflow, mirroring :mod:`cicd_bootstrap.generate` for CI.

The one deploy target implemented today is **local-docker**: deploy onto a
self-hosted runner (the user's own machine) with Docker, using the *recreate*
strategy (stop the old container, run the new one) and an automatic **rollback**
to the previously running image if the new one fails its health check.

Deliberately language-agnostic: a container runs the same regardless of the
source language, so there is no per-language cookbook here -- one well-formed
deploy workflow serves every stack. The only thing that varies is the port the
app listens on, which we read from the repo's Dockerfile ``EXPOSE`` line when
present, defaulting to 8080 (the port every built-in CI cookbook uses).

The approval model is a single toggle:
  * ``auto_deploy=True``  -> deploy straight to production (no gate).
  * ``auto_deploy=False`` -> the deploy job targets a GitHub *environment*
    (``production``); when that environment has required reviewers configured,
    GitHub pauses the run for a human "click to approve" before deploying.
"""

from __future__ import annotations

import os
import re

from pydantic import BaseModel

from .contracts import GeneratedWorkflow, RepoSnapshot
from .cookbooks import dump_workflow

CD_WORKFLOW_PATH = ".github/workflows/deploy.yml"

# Must match the CI workflow name emitted by cookbooks/base.py:render_workflow,
# so CD can trigger automatically when a CI run finishes.
CI_WORKFLOW_NAME = "CI"

DEFAULT_PORT = 8080
# The runner label we registered the laptop under (see the self-hosted runner
# setup). The job targets both "self-hosted" and this label.
RUNNER_LABELS = ["self-hosted", "laptop"]
# The GitHub environment used as the manual-approval gate.
ENVIRONMENT = "production"

# CD "phases", for display parity with CI's build/test/sonar/push.
CD_PHASES = ["pull", "deploy", "health-check", "rollback"]

_EXPOSE_RE = re.compile(r"(?mi)^\s*EXPOSE\s+(\d{2,5})")


class _DetectedRun(BaseModel):
    """LLM-inferred run details for a container whose Dockerfile doesn't say the port."""

    port: int
    reasoning: str = ""


_PORT_SYSTEM = (
    "You are a deployment engineer. Given a container repository's Dockerfile, README, "
    "and file tree, determine the single TCP port the application listens on when the "
    "built image runs. Prefer an explicit signal (EXPOSE, a PORT / ASPNETCORE_HTTP_PORTS "
    "env var, server config, or code that binds a port). If the app has a well-known "
    "default port when unset, use that. If you truly cannot tell, use 8080. Return the port."
)


def _detect_port_llm(snapshot: RepoSnapshot) -> int | None:
    """Ask the LLM which port the container listens on (from the Dockerfile/README/tree).

    Returns None when unavailable (no ANTHROPIC_API_KEY or an API error) so callers fall
    back to the default -- CD must never break just because the LLM assist is off/failing.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        from .llm import call_structured

        manifests = "\n".join(f"\n## {p}\n```\n{c}\n```" for p, c in snapshot.manifests.items())
        user = (
            f"Repository: {snapshot.owner}/{snapshot.name}\n\n"
            "# File tree\n" + "\n".join(snapshot.tree) + "\n\n"
            "# Manifest files (Dockerfile, README, configs)\n" + (manifests or "(none)")
        )
        parsed, _ = call_structured(
            model=os.environ.get("AUTHORING_MODEL", "claude-opus-4-8"),
            system=_PORT_SYSTEM,
            user=user,
            schema=_DetectedRun,
            max_tokens=512,
            timeout=60.0,
        )
        if parsed and 1 <= parsed.port <= 65535:
            print(f"[deploy] LLM inferred port {parsed.port}: {parsed.reasoning[:120]}")
            return parsed.port
    except Exception as exc:  # never break CD on an LLM hiccup -- fall back to the default
        print(f"[deploy] LLM port detection unavailable: {exc}")
    return None


def detect_port(snapshot: RepoSnapshot, *, allow_llm_fallback: bool = False) -> int:
    """Read the app's port from a repo Dockerfile ``EXPOSE`` line, else default.

    The ingest stage already reads a repo Dockerfile into ``manifests`` when one exists,
    so we can honour a project's real port instead of assuming 8080. When there's no
    ``EXPOSE`` and ``allow_llm_fallback`` is set, the LLM works out the port from the
    Dockerfile/README/source (for unusual apps) before we fall back to 8080.
    """
    for path, content in snapshot.manifests.items():
        if path.rsplit("/", 1)[-1] == "Dockerfile":
            m = _EXPOSE_RE.search(content or "")
            if m:
                return int(m.group(1))
    if allow_llm_fallback:
        port = _detect_port_llm(snapshot)
        if port:
            return port
    return DEFAULT_PORT


def generate_cd(
    snapshot: RepoSnapshot,
    *,
    auto_deploy: bool = False,
    auto_handoff: bool = True,
) -> GeneratedWorkflow:
    """Produce the CD workflow for ``snapshot``. No LLM, no per-language branch."""
    content = render_cd_workflow(snapshot, auto_deploy=auto_deploy, auto_handoff=auto_handoff)
    return GeneratedWorkflow(
        path=CD_WORKFLOW_PATH,
        content=content,
        cookbook="local-docker",
        phases=CD_PHASES,
        llm_authored=False,
    )


def render_cd_workflow(
    snapshot: RepoSnapshot,
    *,
    auto_deploy: bool = False,
    auto_handoff: bool = True,
    port: int | None = None,
) -> str:
    """Assemble the full CD workflow YAML for ``snapshot``.

    ``auto_handoff`` controls the CI->CD handoff:
      * True  -> the deploy runs automatically when the CI workflow finishes
                 (a ``workflow_run`` trigger), plus a manual button.
      * False -> the deploy runs ONLY when triggered by hand (``workflow_dispatch``).
    """
    port = port or detect_port(snapshot)
    image = f"ghcr.io/{snapshot.owner.lower()}/{snapshot.name.lower()}"
    app = snapshot.name.lower()  # docker container name
    branch = snapshot.default_branch

    # Job keys are ordered for readability: runs-on, (environment), if, steps.
    job: dict = {"runs-on": RUNNER_LABELS}
    if not auto_deploy:
        # The manual-approval gate: GitHub pauses here for a required reviewer
        # when the `production` environment has reviewers configured.
        job["environment"] = ENVIRONMENT
    # Only deploy when the CI run that triggered us actually succeeded (or when a
    # human triggered CD by hand from the Actions tab).
    job["if"] = (
        "${{ github.event_name == 'workflow_dispatch' "
        "|| github.event.workflow_run.conclusion == 'success' }}"
    )
    job["steps"] = [
        {
            "name": "Determine image tag",
            "id": "img",
            "run": _tag_script(image),
        },
        {
            "name": "Log in to GHCR",
            "run": (
                'echo "${{ secrets.GITHUB_TOKEN }}" | '
                "docker login ghcr.io -u ${{ github.actor }} --password-stdin"
            ),
        },
        {
            "name": "Deploy (recreate) with automatic rollback",
            "run": _deploy_script(app, port),
        },
    ]

    # Auto-handoff adds the workflow_run trigger (deploy right after CI finishes);
    # manual mode leaves only workflow_dispatch (deploy only when you trigger it).
    on_triggers: dict = {}
    if auto_handoff:
        # Chain off CI: when the "CI" workflow finishes on the default branch,
        # run CD. (Guarded on the job to only proceed on success.)
        on_triggers["workflow_run"] = {
            "workflows": [CI_WORKFLOW_NAME],
            "types": ["completed"],
            "branches": [branch],
        }
    # Always allow a manual deploy from the Actions tab (the only trigger in manual mode).
    on_triggers["workflow_dispatch"] = None

    workflow = {
        "name": "CD",
        "on": on_triggers,
        # Read-only token is enough: pull the image, nothing else.
        "permissions": {"contents": "read", "packages": "read"},
        # Never let two deploys of the same app overlap.
        "concurrency": {"group": f"cd-{app}", "cancel-in-progress": False},
        "jobs": {"deploy": job},
    }
    return dump_workflow(
        workflow, header="# Generated by cicd-bootstrap (CD). Review before merging."
    )


def _tag_script(image: str) -> str:
    """Resolve which image tag to deploy: the SHA CI built for this event."""
    return (
        'if [ "${{ github.event_name }}" = "workflow_run" ]; then\n'
        '  SHA="${{ github.event.workflow_run.head_sha }}"\n'
        "else\n"
        '  SHA="${{ github.sha }}"\n'
        "fi\n"
        f'echo "ref={image}:$SHA" >> "$GITHUB_OUTPUT"\n'
        f'echo "Image to deploy: {image}:$SHA"'
    )


def _deploy_script(app: str, port: int) -> str:
    """The recreate-with-rollback deploy step, as a portable /bin/sh script.

    We do NOT `set -e`: failures are handled explicitly so that a bad new image
    always triggers a rollback to the previously running one.
    """
    return f"""\
APP="{app}"
IMAGE="${{{{ steps.img.outputs.ref }}}}"
PORT="{port}"

echo "Deploying $IMAGE  ->  container '$APP'  on port $PORT"

# Remember the image currently serving, so we can roll back to it if needed.
PREV="$(docker inspect --format '{{{{.Config.Image}}}}' "$APP" 2>/dev/null || true)"
echo "Currently running image: ${{PREV:-<none>}}"

# Pull first; if this fails, leave the running deployment untouched.
if ! docker pull "$IMAGE"; then
  echo "Could not pull $IMAGE -- leaving the current deployment untouched."
  exit 1
fi

# Recreate: replace the old container with the new image.
docker rm -f "$APP" >/dev/null 2>&1 || true
docker run -d --name "$APP" --restart unless-stopped -p "$PORT:$PORT" "$IMAGE"

# Health check: the container must stay up AND the port must answer.
healthy=""
code="000"
for i in $(seq 1 15); do
  running="$(docker inspect --format '{{{{.State.Running}}}}' "$APP" 2>/dev/null || echo false)"
  if [ "$running" = "true" ]; then
    code="$(curl -s -o /dev/null -w '%{{http_code}}' "http://localhost:$PORT/" 2>/dev/null || echo 000)"
    if [ "$code" != "000" ]; then healthy="yes"; break; fi
  fi
  sleep 2
done

if [ -n "$healthy" ]; then
  echo "Deploy successful -- '$APP' is up and answering (HTTP $code)."
  exit 0
fi

echo "New container failed its health check. Recent logs:"
docker logs --tail 50 "$APP" 2>&1 || true

if [ -n "$PREV" ] && [ "$PREV" != "$IMAGE" ]; then
  echo "Rolling back to previous image: $PREV"
  docker rm -f "$APP" >/dev/null 2>&1 || true
  docker run -d --name "$APP" --restart unless-stopped -p "$PORT:$PORT" "$PREV"
  echo "Rolled back to $PREV."
else
  echo "No previous image to roll back to (first deploy?)."
fi
exit 1
"""
