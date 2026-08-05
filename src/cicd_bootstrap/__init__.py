"""cicd-bootstrap: a service that adds CI to a repository.

Give it a GitHub repo URL and it:
  1. checks out the repo,
  2. asks an LLM to classify the language and build system,
  3. generates a 4-phase (build, test, sonar, push) CI workflow from a
     deterministic cookbook for that build system, and
  4. opens a pull request adding it, returning the PR number.

The LLM only classifies; the CI file itself is produced by deterministic
cookbooks, so it is reproducible and reviewable. Adding a new language/build
system means adding one small cookbook -- see cookbooks/base.py.
"""

from __future__ import annotations

__version__ = "0.1.0"
