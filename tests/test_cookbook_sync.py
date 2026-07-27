"""Guardrails for the shared cookbook data.

Two things this protects:

1. The service and the bootstrap-ci skill read the *same* ``cookbooks.yaml``.
   The skill ships its own copy (it installs to ~/.claude/skills, detached from
   this repo), so we assert the two copies are identical -- if someone edits one
   and forgets the other, this fails.
2. Every cookbook in the data file -- not just the two the older tests
   parametrised -- generates a valid, four-phase, guarded workflow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ci_bootstrap import cookbooks
from ci_bootstrap.cookbooks.base import DATA_PATH, PUSH_GUARD, SONAR_GUARD, phase_labels
from ci_bootstrap.contracts import Classification, RepoSnapshot
from ci_bootstrap.generate import generate

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_COOKBOOKS = REPO_ROOT / "skill" / "bootstrap-ci" / "references" / "cookbooks.yaml"


def test_skill_and_service_cookbooks_are_in_sync():
    """The skill's vendored copy must match the service's source of truth."""
    assert SKILL_COOKBOOKS.exists(), f"skill copy missing at {SKILL_COOKBOOKS}"
    service = yaml.safe_load(DATA_PATH.read_text())
    skill = yaml.safe_load(SKILL_COOKBOOKS.read_text())
    assert service == skill, (
        "cookbooks.yaml drifted between the service and the skill; re-copy "
        f"{DATA_PATH} to {SKILL_COOKBOOKS}"
    )


def _snap(*, name="demo", branch="main", tree=("pom.xml",)) -> RepoSnapshot:
    return RepoSnapshot(
        repo_url=f"https://github.com/Komali612/{name}", owner="Komali612",
        name=name, default_branch=branch, tree=list(tree),
    )


@pytest.mark.parametrize("build_system", cookbooks.supported())
def test_every_cookbook_generates_a_valid_four_phase_workflow(build_system):
    """Covers all supported build systems (maven, dotnet, pip, go, ...)."""
    wf = generate(
        Classification(language="x", build_system=build_system, test_command="t",
                       confidence=1.0, method="test"),
        _snap(),
    )
    data = yaml.safe_load(wf.content)  # parses -> valid YAML

    assert "on" in data and True not in data  # the on:->True footgun didn't bite
    assert data["permissions"] == {"contents": "read", "packages": "write"}
    assert phase_labels(wf.content) == {"build", "test", "sonar", "push"}

    # placeholders were filled, and the org key was lowercased
    assert "__SONAR_ORG__" not in wf.content and "__SONAR_PROJECT_KEY__" not in wf.content
    assert "komali612" in wf.content and "Komali612_demo" in wf.content

    # every Sonar step guarded on the token; every Push step guarded on the event
    for s in data["jobs"]["ci"]["steps"]:
        name = str(s.get("name", "")).lower()
        if "sonar" in name:
            assert s.get("if") == SONAR_GUARD
            assert s.get("env", {}).get("SONAR_TOKEN") == "${{ secrets.SONAR_TOKEN }}"
        if "push" in name:
            assert s.get("if") == PUSH_GUARD


def test_supported_set_covers_the_four_sample_repos():
    assert set(cookbooks.supported()) >= {"maven", "dotnet", "pip"}
