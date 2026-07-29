"""Orchestration: repo_url -> BootstrapResult.

    ingest  ->  classify  ->  generate  ->  open PR

Each stage can fail; we convert failures into a structured BootstrapResult
(status="error") rather than raising, so callers always get context back --
including the classification/workflow produced before the failure.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from . import telemetry
from .classify import classify
from .config import load_dotenv, sonar_org, sonar_token
from .contracts import BootstrapResult
from .generate import UnsupportedError, generate
from .github import PROpenError, open_pr, resolve_token, set_repo_secret
from .ingest import IngestError, ingest
from .sonar import provision_project


def bootstrap(
    repo_url: str,
    *,
    open_pr_flag: bool = True,
    token: str | None = None,
    allow_llm_fallback: bool = False,
) -> BootstrapResult:
    """Run a bootstrap and record one telemetry event (recording never fails it)."""
    start = time.monotonic()
    result = _run(repo_url, open_pr_flag=open_pr_flag, token=token, allow_llm_fallback=allow_llm_fallback)
    try:
        telemetry.record(result, int((time.monotonic() - start) * 1000))
    except Exception as exc:  # telemetry is best-effort; never break the bootstrap
        print(f"[telemetry] could not record event: {exc}")
    return result


def _run(
    repo_url: str,
    *,
    open_pr_flag: bool = True,
    token: str | None = None,
    allow_llm_fallback: bool = False,
) -> BootstrapResult:
    load_dotenv()
    token = token or resolve_token()

    with tempfile.TemporaryDirectory(prefix="ci-bootstrap-") as tmp:
        workdir = Path(tmp)

        # 1. Ingest
        try:
            snapshot = ingest(repo_url, workdir, token=token)
        except IngestError as exc:
            return BootstrapResult(repo_url=repo_url, status="error", message=str(exc))

        # 2. Classify
        try:
            classification = classify(snapshot)
        except Exception as exc:
            return BootstrapResult(repo_url=repo_url, status="error", message=f"classification failed: {exc}")

        # 3. Generate (optionally via the LLM cookbook fallback)
        try:
            workflow = generate(classification, snapshot, allow_llm_fallback=allow_llm_fallback)
        except UnsupportedError as exc:
            return BootstrapResult(
                repo_url=repo_url, status="error", classification=classification, message=str(exc)
            )
        except Exception as exc:  # LLM fallback failure (AuthorError, API errors, ...)
            return BootstrapResult(
                repo_url=repo_url, status="error", classification=classification,
                message=f"LLM cookbook fallback failed: {exc}",
            )

        # 4. Open PR (unless we were asked only to generate)
        if not open_pr_flag:
            return BootstrapResult(
                repo_url=repo_url, status="generated", classification=classification,
                workflow=workflow, message="workflow generated (no PR requested)",
            )
        if not token:
            return BootstrapResult(
                repo_url=repo_url, status="error", classification=classification, workflow=workflow,
                message="no GitHub token available to open a PR (set GH_TOKEN or run `gh auth login`)",
            )

        # 3.5 Set up SonarCloud so the repo's FIRST scan works, with no manual
        # steps: create the project (Automatic Analysis off by default) and bake
        # the token into the repo's Actions secrets.
        sonar_project = _provision_sonar_project(snapshot)
        sonar_secret_set = _inject_sonar_secret(snapshot, token)

        clone_dir = workdir / snapshot.name
        try:
            pr_number, pr_url, branch = open_pr(snapshot, workflow, clone_dir, token)
        except PROpenError as exc:
            return BootstrapResult(
                repo_url=repo_url, status="error", classification=classification, workflow=workflow,
                sonar_secret_set=sonar_secret_set, sonar_project=sonar_project, message=str(exc),
            )

        return BootstrapResult(
            repo_url=repo_url, status="opened", classification=classification, workflow=workflow,
            branch=branch, pr_number=pr_number, pr_url=pr_url,
            sonar_secret_set=sonar_secret_set, sonar_project=sonar_project,
            message=f"opened PR #{pr_number}",
        )


def _provision_sonar_project(snapshot) -> str | None:
    """Create the repo's SonarCloud project so its first scan doesn't fail.
    Returns "created"/"exists", "error", or None if Sonar isn't configured."""
    org, token = sonar_org(), sonar_token()
    if not (org and token):
        return None
    key = f"{snapshot.owner}_{snapshot.name}"
    try:
        status = provision_project(org, key, snapshot.name, token)
        print(f"[bootstrap] SonarCloud project {key}: {status}")
        return status
    except Exception as exc:  # non-fatal: PR still opens; first scan may need manual setup
        print(f"[bootstrap] could not provision SonarCloud project {key}: {exc}")
        return "error"


def _inject_sonar_secret(snapshot, token: str) -> bool | None:
    """Write SONAR_TOKEN into the repo's Actions secrets when the service holds
    one. Returns True/False on attempt, or None if no token is configured."""
    value = sonar_token()
    if not value:
        return None
    try:
        set_repo_secret(snapshot.owner, snapshot.name, "SONAR_TOKEN", value, token)
        print(f"[bootstrap] set SONAR_TOKEN secret on {snapshot.owner}/{snapshot.name}")
        return True
    except Exception as exc:  # non-fatal: the PR still opens; Sonar just stays skipped
        print(f"[bootstrap] could not set SONAR_TOKEN on {snapshot.owner}/{snapshot.name}: {exc}")
        return False
