"""Generate stage: turn a Classification into a CI workflow via a cookbook.

This is the deterministic half. We look up the cookbook for the classified
build system and render the 4-phase workflow. If there is no cookbook for the
classification, we raise UnsupportedError -- we never guess or fall back to an
LLM writing YAML.
"""

from __future__ import annotations

from . import cookbooks
from .contracts import Classification, GeneratedWorkflow, RepoSnapshot

WORKFLOW_PATH = ".github/workflows/ci.yml"


class UnsupportedError(Exception):
    """Raised when no cookbook matches the classification."""


def generate(classification: Classification, snapshot: RepoSnapshot) -> GeneratedWorkflow:
    cookbook = cookbooks.get(classification.build_system)
    if cookbook is None:
        raise UnsupportedError(
            f"no cookbook for build system {classification.build_system!r} "
            f"(language {classification.language!r}). "
            f"Supported: {', '.join(cookbooks.supported())}."
        )

    content = cookbooks.render_workflow(cookbook, snapshot)
    return GeneratedWorkflow(path=WORKFLOW_PATH, content=content, cookbook=cookbook.key)
