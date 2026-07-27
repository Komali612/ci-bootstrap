# ci-bootstrap

A service that **adds CI to a repository**. Give it a GitHub repo URL and it:

1. **checks out** the repo,
2. asks an **LLM to classify** the language and build system,
3. generates a **4-phase CI workflow** (`build → test → sonar → push`) from a
   deterministic **cookbook** for that build system, and
4. opens a **pull request** adding `.github/workflows/ci.yml`, returning the PR number.

The LLM only classifies. The CI file itself is produced by deterministic
cookbooks, so it is reproducible, reviewable, and testable offline.

```
repo_url → ingest → classify (LLM) → generate (cookbook) → open PR → PR number
```

## Design

| Stage | Module | What it does |
|-------|--------|--------------|
| Ingest | `ingest.py` | Shallow-clone the repo → a small snapshot (file tree + manifest contents). Errors if it can't reach the repo. |
| Classify | `classify.py` | LLM decides `language` + `build_system` + `test_command`; deterministic heuristic fallback. |
| Generate | `generate.py` + `cookbooks/` | Look up the cookbook for the build system and render the workflow. **No cookbook → `UnsupportedError`.** |
| Open PR | `github.py` | Commit on a branch, push, open a PR. Assumes push access; errors otherwise. |

The four phases live in **one place** — `cookbooks/base.py` — and are always
emitted. Sonar is skipped until a `SONAR_TOKEN` secret is set; the image push
runs only on merges to the default branch. These guards are structural, not
selectable.

## Adding support for a new language / build system

Write one small file under `src/ci_bootstrap/cookbooks/` and register it:

```python
from .base import Cookbook, register

register(Cookbook(
    key="npm", language="javascript", display_name="Node.js (npm)",
    setup=[{"name": "Set up Node", "uses": "actions/setup-node@v4", "with": {"node-version": "20"}}],
    build=["npm ci"],
    test=["npm test"],
    sonar=[{"name": "Sonar scan", "uses": "sonarsource/sonarqube-scan-action@v3"}],
    default_dockerfile="FROM node:20-slim\n...",
))
```

Then add `from . import npm` to `cookbooks/__init__.py`. Nothing else changes —
the 4-phase skeleton and guards are inherited from `base.py`. Currently shipped:
**Java (Maven)** and **.NET (C#)**.

## Running

Set secrets once in a gitignored `.env` at the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...
GH_TOKEN=ghp_...
```

Run the service (the primary interface) and open http://127.0.0.1:8000/:

```bash
ci-bootstrap --serve
```

Or use the CLI:

```bash
ci-bootstrap https://github.com/owner/repo            # classify, generate, open PR
ci-bootstrap https://github.com/owner/repo --no-pr    # generate only, print the YAML
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Generation is deterministic, so the suite asserts the exact workflow structure
(all four phases, ordering, guards, GHCR target) with no network or LLM.
