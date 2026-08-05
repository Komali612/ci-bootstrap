"""Load configuration from a .env file so secrets are set once, not per run.

Looked for in the current directory and this repo's root. Real environment
variables always win over the file, so you can still override per-invocation
with `ANTHROPIC_API_KEY=... cicd-bootstrap ...`.

Set once in a gitignored `.env` at the repo root:

    ANTHROPIC_API_KEY=sk-ant-...
    GH_TOKEN=ghp_...
    SONAR_ORG=my-sonar-org        # baked into every generated workflow
    SONAR_TOKEN=<sonarcloud token> # injected into each bootstrapped repo's secrets
"""

from __future__ import annotations

import os
from pathlib import Path


def _candidate_paths() -> list[Path]:
    # config.py -> cicd_bootstrap -> src -> <repo root>
    repo_root = Path(__file__).resolve().parents[2]
    return [Path.cwd() / ".env", repo_root / ".env"]


def load_dotenv() -> str | None:
    """Apply the first .env file found. Returns its path, or None if absent."""
    for path in _candidate_paths():
        if path.is_file():
            _apply(path)
            return str(path)
    return None


def sonar_org() -> str | None:
    """The SonarCloud organization key baked into every generated workflow.

    Set once via SONAR_ORG. If unset, the generator falls back to the repo
    owner (lowercased) -- the SonarCloud convention for GitHub-imported orgs.
    """
    return (os.environ.get("SONAR_ORG") or "").strip() or None


def sonar_token() -> str | None:
    """The SonarCloud analysis token, held by the service (not per repo).

    Set once via SONAR_TOKEN. When present, the service writes it into each
    bootstrapped repo's Actions secrets so developers never set it by hand.
    """
    return (os.environ.get("SONAR_TOKEN") or "").strip() or None


def _apply(path: Path) -> None:
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:  # a real env var takes precedence
            os.environ[key] = val
