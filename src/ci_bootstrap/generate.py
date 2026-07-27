"""Generate stage: turn a Classification into a CI workflow via a cookbook.

This is the deterministic half. We look up the cookbook for the classified build
system and render the 4-phase workflow.

If there is no cookbook, the default is to raise UnsupportedError -- we never
guess. But the caller may opt in to an LLM fallback (allow_llm_fallback=True):
the LLM fills in ONLY the cookbook's language-specific fields, and the SAME
deterministic skeleton assembles the phases and guards around them. Even then,
the LLM never writes the workflow YAML itself.
"""

from __future__ import annotations

from . import cookbooks
from .contracts import Classification, GeneratedWorkflow, RepoSnapshot

WORKFLOW_PATH = ".github/workflows/ci.yml"


class UnsupportedError(Exception):
    """Raised when no cookbook matches the classification (and no fallback was allowed)."""


def generate(
    classification: Classification,
    snapshot: RepoSnapshot,
    *,
    allow_llm_fallback: bool = False,
) -> GeneratedWorkflow:
    cookbook = cookbooks.get(classification.build_system)
    llm_authored = False
    usage: dict = {}

    if cookbook is None:
        if not allow_llm_fallback:
            raise UnsupportedError(
                f"no cookbook for build system {classification.build_system!r} "
                f"(language {classification.language!r}). "
                f"Supported: {', '.join(cookbooks.supported())}. "
                f"Enable the LLM fallback to generate one."
            )
        # Import lazily so the deterministic path never depends on the LLM client.
        from .author import author_cookbook

        cookbook, usage = author_cookbook(snapshot, classification)
        llm_authored = True

    content = cookbooks.render_workflow(cookbook, snapshot)
    return GeneratedWorkflow(
        path=WORKFLOW_PATH,
        content=content,
        cookbook=cookbook.key,
        llm_authored=llm_authored,
        llm_input_tokens=usage.get("input_tokens"),
        llm_output_tokens=usage.get("output_tokens"),
    )
