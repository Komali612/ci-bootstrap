"""Harness CD integration -- deploy the CI-built image via Harness instead of
GitHub Actions.

This is the Harness counterpart to :mod:`cicd_bootstrap.deploy` (which emits a
GitHub Actions ``deploy.yml``). Here we generate a **Harness pipeline** and drive
it through the Harness API. CI is unchanged: GitHub Actions still builds and
pushes ``ghcr.io/<owner>/<name>:<sha>`` to GHCR; Harness pulls that image and
runs it on the laptop through a **delegate** (the on-machine worker, the Harness
twin of a self-hosted runner).

The delegate runs a shell step (``onDelegate: true``, pinned to the ``laptop``
delegate selector) that drives the host Docker via the mounted socket, using the
same *recreate + health-check + rollback* strategy as the GitHub Actions path.

Config comes from ``.env`` (see ``.env.example``):
  HARNESS_ACCOUNT_ID, HARNESS_API_KEY, HARNESS_MANAGER_HOST,
  HARNESS_ORG (default "default"), HARNESS_PROJECT (default "default_project").

Nothing here is secret in transit beyond the API key, which is only ever sent in
the ``x-api-key`` header, never logged.
"""

from __future__ import annotations

import os
import re
import time

import httpx
import yaml

from .config import load_dotenv
from .deploy import detect_port
from .contracts import RepoSnapshot

# Where the pipeline lives when stored in the repo (Git Experience / "remote").
HARNESS_PIPELINE_PATH = ".harness/deploy.yaml"
# The delegate selector we tag the laptop delegate with (see add-harness-delegate.sh).
DELEGATE_SELECTOR = "laptop"


class HarnessError(Exception):
    """Raised when a Harness API call fails or config is missing."""


# --- config ---------------------------------------------------------------

class HarnessConfig:
    def __init__(self) -> None:
        load_dotenv()
        self.account = os.environ.get("HARNESS_ACCOUNT_ID", "").strip()
        self.api_key = os.environ.get("HARNESS_API_KEY", "").strip()
        self.host = (os.environ.get("HARNESS_MANAGER_HOST") or "https://app.harness.io").rstrip("/")
        self.org = os.environ.get("HARNESS_ORG", "default").strip() or "default"
        self.project = os.environ.get("HARNESS_PROJECT", "default_project").strip() or "default_project"

    def require(self) -> "HarnessConfig":
        if not self.account or not self.api_key:
            raise HarnessError(
                "Harness is not configured: set HARNESS_ACCOUNT_ID and HARNESS_API_KEY in .env"
            )
        return self

    @property
    def pipeline_base(self) -> str:
        return f"{self.host}/pipeline/api"

    @property
    def ng_base(self) -> str:
        return f"{self.host}/ng/api"

    @property
    def scope(self) -> dict[str, str]:
        return {
            "accountIdentifier": self.account,
            "orgIdentifier": self.org,
            "projectIdentifier": self.project,
        }

    def headers(self, *, yaml_body: bool = False) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/yaml" if yaml_body else "application/json",
        }


def identifier(name: str) -> str:
    """A valid Harness identifier: alphanumerics/underscore, not starting with a digit."""
    ident = re.sub(r"[^0-9A-Za-z_]", "_", name.strip())
    if not ident or ident[0].isdigit():
        ident = "_" + ident
    return ident


# --- pipeline generation --------------------------------------------------

def build_deploy_script(owner: str, name: str, port: int) -> str:
    """The recreate-with-rollback deploy step the delegate runs (drives host Docker).

    Mirrors :func:`cicd_bootstrap.deploy._deploy_script`, with two delegate-specific
    changes: the image tag comes from a pipeline variable ``imageTag``, and the
    health check hits ``host.docker.internal`` (the delegate is a separate
    container, so its own ``localhost`` can't reach the app published on the host).
    """
    image = f"ghcr.io/{owner.lower()}/{name.lower()}"
    app = name.lower()
    return f"""\
set +e
TAG="<+pipeline.variables.imageTag>"
IMAGE="{image}:$TAG"
APP="{app}"
PORT="{port}"
echo "Deploying $IMAGE  ->  container '$APP' on port $PORT"

# Remember the currently-running image so we can roll back to it if needed.
PREV="$(docker inspect --format '{{{{.Config.Image}}}}' "$APP" 2>/dev/null || true)"
echo "Currently running image: ${{PREV:-<none>}}"

if ! docker pull "$IMAGE"; then
  echo "Could not pull $IMAGE -- leaving the current deployment untouched."
  exit 1
fi

docker rm -f "$APP" >/dev/null 2>&1 || true
docker run -d --name "$APP" --restart unless-stopped -p "$PORT:$PORT" "$IMAGE"

# Health check from the delegate: reach the app on the HOST via host.docker.internal.
healthy=""; code="000"
for i in $(seq 1 15); do
  running="$(docker inspect --format '{{{{.State.Running}}}}' "$APP" 2>/dev/null || echo false)"
  if [ "$running" = "true" ]; then
    code="$(curl -s -o /dev/null -w '%{{http_code}}' "http://host.docker.internal:$PORT/" 2>/dev/null || echo 000)"
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


def _deploy_stage(owner: str, name: str, port: int) -> dict:
    return {
        "stage": {
            "name": "Deploy",
            "identifier": "Deploy",
            "type": "Custom",
            "spec": {
                "execution": {
                    "steps": [
                        {
                            "step": {
                                "type": "ShellScript",
                                "name": "Deploy to laptop",
                                "identifier": "Deploy",
                                "timeout": "15m",
                                "spec": {
                                    "shell": "Bash",
                                    "onDelegate": True,
                                    "delegateSelectors": [DELEGATE_SELECTOR],
                                    "source": {
                                        "type": "Inline",
                                        "spec": {"script": build_deploy_script(owner, name, port)},
                                    },
                                    "environmentVariables": [],
                                    "outputVariables": [],
                                },
                            }
                        }
                    ]
                }
            },
            "tags": {},
        }
    }


def _approval_stage() -> dict:
    return {
        "stage": {
            "name": "Approval",
            "identifier": "Approval",
            "type": "Approval",
            "spec": {
                "execution": {
                    "steps": [
                        {
                            "step": {
                                "type": "HarnessApproval",
                                "name": "Approve deploy",
                                "identifier": "Approve",
                                "timeout": "1d",
                                "spec": {
                                    "approvalMessage": "Approve deployment to the laptop?",
                                    "includePipelineExecutionHistory": True,
                                    "isAutoRejectEnabled": False,
                                    "approvers": {
                                        "userGroups": ["_project_all_users"],
                                        "minimumCount": 1,
                                        "disallowPipelineExecutor": False,
                                    },
                                    "approverInputs": [],
                                },
                            }
                        }
                    ]
                }
            },
            "tags": {},
        }
    }


def build_pipeline(owner: str, name: str, port: int, *, auto_deploy: bool, org: str, project: str) -> dict:
    """The Harness pipeline dict: (optional approval ->) deploy on the laptop delegate."""
    stages: list[dict] = []
    if not auto_deploy:
        stages.append(_approval_stage())
    stages.append(_deploy_stage(owner, name, port))
    return {
        "pipeline": {
            "name": f"Deploy {name}",
            "identifier": identifier(f"deploy_{name}"),
            "projectIdentifier": project,
            "orgIdentifier": org,
            "tags": {},
            "stages": stages,
            # imageTag is supplied at run time (by a person, or by the CI artifact trigger).
            "variables": [
                {"name": "imageTag", "type": "String", "description": "GHCR image tag (the CI commit SHA)",
                 "required": True, "value": "<+input>"}
            ],
        }
    }


def build_pipeline_yaml(snapshot: RepoSnapshot, *, auto_deploy: bool = True, port: int | None = None,
                        allow_llm_fallback: bool = False) -> str:
    cfg = HarnessConfig()
    port = port or detect_port(snapshot, allow_llm_fallback=allow_llm_fallback)
    pipe = build_pipeline(
        snapshot.owner, snapshot.name, port,
        auto_deploy=auto_deploy, org=cfg.org, project=cfg.project,
    )
    return yaml.dump(pipe, sort_keys=False, default_flow_style=False, width=4096)


# --- Harness API ----------------------------------------------------------

def _raise_for(resp: httpx.Response, what: str) -> dict:
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:400]}
    if resp.status_code >= 300 or body.get("status") == "ERROR":
        msgs = body.get("responseMessages") or body.get("message") or body.get("raw")
        raise HarnessError(f"{what} failed ({resp.status_code}): {msgs}")
    return body


def create_pipeline(pipeline_yaml: str, cfg: HarnessConfig | None = None) -> str:
    """Create (or fail if exists) a pipeline from YAML. Returns its identifier."""
    cfg = (cfg or HarnessConfig()).require()
    resp = httpx.post(
        f"{cfg.pipeline_base}/pipelines/v2",
        params=cfg.scope, headers=cfg.headers(yaml_body=True),
        content=pipeline_yaml, timeout=60,
    )
    body = _raise_for(resp, "create pipeline")
    return (body.get("data") or {}).get("identifier", "")


def update_pipeline(pipeline_id: str, pipeline_yaml: str, cfg: HarnessConfig | None = None) -> None:
    """Update an existing pipeline's YAML (idempotent re-provisioning)."""
    cfg = (cfg or HarnessConfig()).require()
    resp = httpx.put(
        f"{cfg.pipeline_base}/pipelines/v2/{pipeline_id}",
        params=cfg.scope, headers=cfg.headers(yaml_body=True),
        content=pipeline_yaml, timeout=60,
    )
    _raise_for(resp, "update pipeline")


def upsert_pipeline(pipeline_yaml: str, pipeline_id: str, cfg: HarnessConfig | None = None) -> str:
    """Create the pipeline, or update it if it already exists."""
    cfg = (cfg or HarnessConfig()).require()
    try:
        return create_pipeline(pipeline_yaml, cfg)
    except HarnessError:
        update_pipeline(pipeline_id, pipeline_yaml, cfg)
        return pipeline_id


def execute_pipeline(pipeline_id: str, image_tag: str, cfg: HarnessConfig | None = None) -> str:
    """Trigger a run, passing the image tag as the runtime input. Returns planExecutionId."""
    cfg = (cfg or HarnessConfig()).require()
    inputs = yaml.dump(
        {"pipeline": {"identifier": pipeline_id,
                      "variables": [{"name": "imageTag", "type": "String", "value": image_tag}]}},
        sort_keys=False,
    )
    resp = httpx.post(
        f"{cfg.pipeline_base}/pipeline/execute/{pipeline_id}",
        params={**cfg.scope, "moduleType": "cd"},
        headers=cfg.headers(yaml_body=True), content=inputs, timeout=60,
    )
    body = _raise_for(resp, "execute pipeline")
    data = body.get("data") or {}
    return data.get("planExecutionId") or (data.get("planExecution") or {}).get("uuid", "")


def execution_status(plan_execution_id: str, cfg: HarnessConfig | None = None) -> str:
    """Current status of a run: Running/Success/Failed/Aborted/etc."""
    cfg = (cfg or HarnessConfig()).require()
    resp = httpx.get(
        f"{cfg.pipeline_base}/pipelines/execution/v2/{plan_execution_id}",
        params=cfg.scope, headers=cfg.headers(), timeout=30,
    )
    body = _raise_for(resp, "execution status")
    return ((body.get("data") or {}).get("pipelineExecutionSummary") or {}).get("status", "Unknown")


def wait_for_execution(
    plan_execution_id: str, cfg: HarnessConfig | None = None, *, timeout_s: int = 600, interval_s: int = 10
) -> str:
    """Poll until the run reaches a terminal status; return it."""
    cfg = cfg or HarnessConfig()
    terminal = {"Success", "Failed", "Aborted", "Errored", "Expired", "ApprovalRejected", "IgnoreFailed"}
    deadline = time.monotonic() + timeout_s
    status = "Unknown"
    while time.monotonic() < deadline:
        status = execution_status(plan_execution_id, cfg)
        if status in terminal:
            return status
        time.sleep(interval_s)
    return status


# --- Git storage: secret + GitHub connector + remote (Git-stored) pipeline ----
# For "pipeline stored in Git" (Harness Git Experience), Harness needs a GitHub
# connector to read/write the repo, which needs the GitHub token stored as a
# Harness secret. Then we create the pipeline as a REMOTE entity: Harness itself
# writes the YAML into the repo. The token is only ever sent to Harness, never logged.

TOKEN_SECRET_NAME = "cicd github token"
GITHUB_CONNECTOR_ID = "cicd_github"


def ensure_secret_text(name: str, value: str, cfg: HarnessConfig | None = None) -> str:
    """Create (or update) an inline text secret; returns its identifier."""
    cfg = (cfg or HarnessConfig()).require()
    ident = identifier(name)
    body = {"secret": {
        "type": "SecretText", "name": name, "identifier": ident,
        "orgIdentifier": cfg.org, "projectIdentifier": cfg.project,
        "spec": {"secretManagerIdentifier": "harnessSecretManager", "valueType": "Inline", "value": value},
    }}
    resp = httpx.post(f"{cfg.ng_base}/v2/secrets", params=cfg.scope, headers=cfg.headers(), json=body, timeout=30)
    if resp.status_code < 300 and resp.json().get("status") == "SUCCESS":
        return ident
    resp = httpx.put(f"{cfg.ng_base}/v2/secrets/{ident}", params=cfg.scope, headers=cfg.headers(), json=body, timeout=30)
    _raise_for(resp, "ensure secret")
    return ident


def ensure_github_connector(
    owner: str, cfg: HarnessConfig | None = None, *,
    token_ref: str | None = None, validation_repo: str | None = None,
) -> str:
    """Create (or update) an account-level GitHub connector; returns its identifier."""
    cfg = (cfg or HarnessConfig()).require()
    token_ref = token_ref or identifier(TOKEN_SECRET_NAME)
    spec = {
        "type": "Account", "url": f"https://github.com/{owner}",
        "authentication": {"type": "Http", "spec": {
            "type": "UsernameToken", "spec": {"username": owner, "tokenRef": token_ref}}},
        "apiAccess": {"type": "Token", "spec": {"tokenRef": token_ref}},
        "executeOnDelegate": False,
    }
    if validation_repo:
        spec["validationRepo"] = validation_repo
    body = {"connector": {
        "name": "cicd github", "identifier": GITHUB_CONNECTOR_ID, "type": "Github",
        "orgIdentifier": cfg.org, "projectIdentifier": cfg.project, "spec": spec,
    }}
    resp = httpx.post(f"{cfg.ng_base}/connectors", params=cfg.scope, headers=cfg.headers(), json=body, timeout=30)
    if resp.status_code < 300 and resp.json().get("status") == "SUCCESS":
        return GITHUB_CONNECTOR_ID
    resp = httpx.put(f"{cfg.ng_base}/connectors", params=cfg.scope, headers=cfg.headers(), json=body, timeout=30)
    _raise_for(resp, "ensure github connector")
    return GITHUB_CONNECTOR_ID


def create_pipeline_remote(
    pipeline_yaml: str, pipeline_id: str, *,
    connector_ref: str, repo: str, branch: str,
    file_path: str = HARNESS_PIPELINE_PATH,
    commit_msg: str = "cicd-bootstrap: add Harness deploy pipeline",
    cfg: HarnessConfig | None = None,
) -> str:
    """Create a REMOTE (Git-stored) pipeline: Harness writes the YAML into the repo."""
    cfg = (cfg or HarnessConfig()).require()
    params = {
        **cfg.scope, "storeType": "REMOTE", "connectorRef": connector_ref,
        "repoName": repo, "branch": branch, "filePath": file_path,
        "commitMsg": commit_msg, "isNewBranch": "false",
    }
    resp = httpx.post(
        f"{cfg.pipeline_base}/pipelines/v2",
        params=params, headers=cfg.headers(yaml_body=True), content=pipeline_yaml, timeout=60,
    )
    try:
        body = _raise_for(resp, "create remote pipeline")
    except HarnessError as exc:
        # Idempotent: if the pipeline is already stored in the repo, that's fine.
        low = str(exc).lower()
        if "already" in low or "duplicate" in low or "exist" in low:
            return pipeline_id
        raise
    return (body.get("data") or {}).get("identifier", "") or pipeline_id


def store_pipeline_in_repo(
    snapshot: RepoSnapshot, github_token: str, *,
    auto_deploy: bool = True, branch: str | None = None, cfg: HarnessConfig | None = None,
    allow_llm_fallback: bool = False,
) -> str:
    """One call: ensure the token secret + GitHub connector, then create the deploy
    pipeline as a Git-stored file in the repo (Harness commits ``.harness/deploy.yaml``).
    Returns the pipeline identifier."""
    cfg = (cfg or HarnessConfig()).require()
    branch = branch or snapshot.default_branch
    token_ref = ensure_secret_text(TOKEN_SECRET_NAME, github_token, cfg)
    connector = ensure_github_connector(snapshot.owner, cfg, token_ref=token_ref, validation_repo=snapshot.name)
    pipeline_yaml = build_pipeline_yaml(snapshot, auto_deploy=auto_deploy, allow_llm_fallback=allow_llm_fallback)
    pid = identifier(f"deploy_{snapshot.name}")
    return create_pipeline_remote(
        pipeline_yaml, pid, connector_ref=connector, repo=snapshot.name, branch=branch, cfg=cfg,
    )


# --- webhook trigger: "CI pings Harness to deploy" -------------------------
# Rather than have Harness poll GHCR (which needs a heavy service-based pipeline),
# CI pings a custom webhook at the end of a successful run, passing the image tag.
# The trigger maps the pinged tag onto the pipeline's imageTag input.

WEBHOOK_TRIGGER_ID = "ci_notify"


def ensure_webhook_trigger(pipeline_id: str, cfg: HarnessConfig | None = None, *,
                           trigger_id: str | None = None, branch: str = "main") -> str:
    """Create (or update) the custom webhook trigger on ``pipeline_id``; return its URL.

    Trigger identifiers are unique per *project*, so we derive a per-pipeline id.
    Remote (Git-stored) pipelines require ``pipelineBranchName`` so Harness can read
    the pipeline from Git to validate the trigger.
    """
    cfg = (cfg or HarnessConfig()).require()
    trigger_id = trigger_id or f"notify_{identifier(pipeline_id)}"
    input_yaml = yaml.dump(
        {"pipeline": {"identifier": pipeline_id,
                      "variables": [{"name": "imageTag", "type": "String", "value": "<+trigger.payload.tag>"}]}},
        sort_keys=False,
    )
    trig = {"trigger": {
        "name": "CI notify", "identifier": trigger_id, "enabled": True,
        "orgIdentifier": cfg.org, "projectIdentifier": cfg.project,
        "pipelineIdentifier": pipeline_id, "pipelineBranchName": branch,
        "source": {"type": "Webhook", "spec": {"type": "Custom",
                   "spec": {"payloadConditions": [], "headerConditions": []}}},
        "inputYaml": input_yaml,
    }}
    body = yaml.dump(trig, sort_keys=False, default_flow_style=False, width=4096)
    params = {**cfg.scope, "targetIdentifier": pipeline_id}
    resp = httpx.post(f"{cfg.pipeline_base}/triggers", params=params,
                      headers=cfg.headers(yaml_body=True), content=body, timeout=30)
    try:
        _raise_for(resp, "create webhook trigger")
    except HarnessError as exc:
        low = str(exc).lower()
        if "already" in low or "duplicate" in low or "exist" in low:  # idempotent -> update
            resp = httpx.put(f"{cfg.pipeline_base}/triggers/{trigger_id}", params=params,
                             headers=cfg.headers(yaml_body=True), content=body, timeout=30)
            _raise_for(resp, "update webhook trigger")
        else:
            raise
    return get_trigger_webhook_url(pipeline_id, trigger_id, cfg)


def get_trigger_webhook_url(pipeline_id: str, trigger_id: str | None = None,
                            cfg: HarnessConfig | None = None) -> str:
    cfg = (cfg or HarnessConfig()).require()
    trigger_id = trigger_id or f"notify_{identifier(pipeline_id)}"
    resp = httpx.get(f"{cfg.pipeline_base}/triggers/{trigger_id}",
                     params={**cfg.scope, "targetIdentifier": pipeline_id}, headers=cfg.headers(), timeout=30)
    body = _raise_for(resp, "get trigger")
    return (body.get("data") or {}).get("webhookUrl", "")


# GitHub Actions workflow that pings the Harness webhook after CI succeeds, so
# Harness deploys the image CI just pushed. Committed to the repo alongside CI.
NOTIFY_WORKFLOW_PATH = ".github/workflows/notify-harness.yml"


def render_notify_workflow(ci_workflow_name: str = "CI", branch: str = "main") -> str:
    """A tiny workflow: on CI success, POST the built SHA to the Harness webhook."""
    return f"""\
# Generated by cicd-bootstrap (Harness CD). Pings Harness to deploy the image CI
# just pushed. The webhook URL is stored as the HARNESS_WEBHOOK_URL repo secret.
name: Notify Harness
on:
  workflow_run:
    workflows: ["{ci_workflow_name}"]
    types: [completed]
jobs:
  notify:
    if: ${{{{ github.event.workflow_run.conclusion == 'success'
        && github.event.workflow_run.head_branch == '{branch}' }}}}
    runs-on: ubuntu-latest
    steps:
      - name: Ping Harness to deploy this image
        run: |
          curl -sS -X POST "${{{{ secrets.HARNESS_WEBHOOK_URL }}}}" \\
            -H "Content-Type: application/json" \\
            -d "{{\\"tag\\":\\"${{{{ github.event.workflow_run.head_sha }}}}\\"}}"
"""


def trigger_deploy(webhook_url: str, image_tag: str) -> bool:
    """Ping the pipeline's webhook to deploy a specific image tag -- exactly what the
    CI ``notify-harness`` workflow does. Lets us deploy the image already in GHCR."""
    resp = httpx.post(webhook_url, json={"tag": image_tag},
                      headers={"Content-Type": "application/json"}, timeout=30)
    return resp.status_code < 300


def deploy_via_harness(
    snapshot: RepoSnapshot, github_token: str, *,
    auto_deploy: bool = True, branch: str | None = None, cfg: HarnessConfig | None = None,
    allow_llm_fallback: bool = False,
) -> dict[str, str]:
    """Full Harness CD provisioning for a repo: secret + GitHub connector + the
    Git-stored deploy pipeline + the CI-notify webhook trigger. Returns
    ``{"pipeline_id", "webhook_url"}``. Caller stores the URL as a repo secret and
    opens a PR adding the notify workflow (see core.add_cd_harness)."""
    cfg = (cfg or HarnessConfig()).require()
    branch = branch or snapshot.default_branch
    pid = store_pipeline_in_repo(snapshot, github_token, auto_deploy=auto_deploy, branch=branch, cfg=cfg,
                                 allow_llm_fallback=allow_llm_fallback)
    webhook_url = ensure_webhook_trigger(pid, cfg, branch=branch)
    return {"pipeline_id": pid, "webhook_url": webhook_url}
