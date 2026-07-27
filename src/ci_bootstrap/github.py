"""Open a pull request that adds the generated workflow.

We commit the workflow on a fresh branch in the already-cloned repo, push it
with a token-authenticated remote, and open a PR via the GitHub REST API. We
assume the token can push to the repo; if it cannot, the push fails and we
raise -- we do not fork or work around it.

The token is only ever placed in the push remote URL, never printed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

from .contracts import GeneratedWorkflow, RepoSnapshot

API = "https://api.github.com"
BRANCH_PREFIX = "ci-bootstrap/add-ci"


class PROpenError(Exception):
    """Raised when the branch cannot be pushed or the PR cannot be opened."""


class SecretError(Exception):
    """Raised when a repository Actions secret cannot be written."""


def set_repo_secret(owner: str, name: str, secret_name: str, value: str, token: str) -> None:
    """Store `value` as an Actions secret on owner/name.

    GitHub requires the value encrypted for the repo's Actions public key with a
    libsodium sealed box. Needs a token with admin (secrets:write) on the repo.
    The secret value is never logged.
    """
    key = httpx.get(
        f"{API}/repos/{owner}/{name}/actions/secrets/public-key",
        headers=_headers(token), timeout=30,
    )
    if key.status_code >= 300:
        raise SecretError(f"fetch public key failed: {key.status_code} {key.text[:200]}")
    pub = key.json()
    payload = {"encrypted_value": _seal(pub["key"], value), "key_id": pub["key_id"]}
    put = httpx.put(
        f"{API}/repos/{owner}/{name}/actions/secrets/{secret_name}",
        headers=_headers(token), json=payload, timeout=30,
    )
    if put.status_code >= 300:
        raise SecretError(f"set secret {secret_name} failed: {put.status_code} {put.text[:200]}")


def _seal(public_key_b64: str, value: str) -> str:
    """libsodium sealed box → base64, the exact format GitHub expects."""
    import base64

    from nacl import encoding, public

    pk = public.PublicKey(public_key_b64.encode(), encoder=encoding.Base64Encoder)
    sealed = public.SealedBox(pk).encrypt(value.encode())
    return base64.b64encode(sealed).decode()


def resolve_token() -> str | None:
    """Find a GitHub token: env first, then the gh CLI."""
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(var):
            return os.environ[var].strip()
    # A subprocess may have a narrower PATH than the interactive shell (common
    # under conda), so try known install locations too.
    for exe in (shutil.which("gh"), "/opt/homebrew/bin/gh", "/usr/local/bin/gh", "/usr/bin/gh"):
        if not exe:
            continue
        try:
            out = subprocess.run([exe, "auth", "token"], capture_output=True, text=True, timeout=15)
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            continue
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    return None


def open_pr(
    snapshot: RepoSnapshot,
    workflow: GeneratedWorkflow,
    clone_dir: Path,
    token: str,
) -> tuple[int, str, str]:
    """Commit the workflow on a fresh branch, push it, and open a PR.

    Returns (pr_number, pr_url, branch).
    """
    owner, name, base = snapshot.owner, snapshot.name, snapshot.default_branch
    branch = f"{BRANCH_PREFIX}-{int(time.time())}"

    target = clone_dir / workflow.path
    if target.exists():
        target = target.with_name("ci-bootstrap.yml")  # don't clobber an existing ci.yml
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(workflow.content)

    _git(clone_dir, "checkout", "-b", branch)
    _git(clone_dir, "add", str(target.relative_to(clone_dir)))
    _git(
        clone_dir, "-c", "user.name=ci-bootstrap[bot]",
        "-c", "user.email=ci-bootstrap@users.noreply.github.com",
        "commit", "-m", f"ci: add {workflow.cookbook} CI workflow (build, test, sonar, push)",
    )

    push_url = f"https://x-access-token:{token}@github.com/{owner}/{name}.git"
    try:
        _git(clone_dir, "push", push_url, f"{branch}:{branch}")
    except PROpenError as exc:
        raise PROpenError(
            f"could not push to {owner}/{name} (do you have write access?): {_redact(str(exc), token)}"
        ) from None

    resp = httpx.post(
        f"{API}/repos/{owner}/{name}/pulls",
        headers=_headers(token),
        json={
            "title": "ci: add CI workflow (via ci-bootstrap)",
            "head": branch,
            "base": base,
            "body": _pr_body(snapshot, workflow),
        },
        timeout=30,
    )
    if resp.status_code >= 300:
        raise PROpenError(f"GitHub API {resp.status_code} opening PR: {resp.text[:400]}")
    data = resp.json()
    return data["number"], data["html_url"], branch


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}


def _pr_body(snapshot: RepoSnapshot, workflow: GeneratedWorkflow) -> str:
    return (
        "## 🤖 ci-bootstrap\n\n"
        f"Adds `{workflow.path}` to **{snapshot.owner}/{snapshot.name}**, generated from the "
        f"**{workflow.cookbook}** cookbook after classifying the repository.\n\n"
        "The workflow defines all four CI phases: **build → test → sonar → push**. "
        "Sonar runs once a `SONAR_TOKEN` secret is set; the image push runs on merges to "
        f"`{snapshot.default_branch}`.\n\n"
        "Review and merge if it looks right."
    )


def _git(cwd: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, timeout=120
        ).stdout
    except subprocess.CalledProcessError as exc:
        raise PROpenError(f"git {' '.join(args[:2])} failed: {exc.stderr.strip()[:300]}") from exc


def _redact(text: str, token: str) -> str:
    return text.replace(token, "***") if token else text
