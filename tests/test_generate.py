"""Offline tests for the deterministic generator and cookbooks.

Because generation is deterministic, we can assert on the exact structure of the
produced workflow without any network or LLM.
"""

from __future__ import annotations

import pytest
import yaml

from ci_bootstrap import cookbooks
from ci_bootstrap.classify import classify_with_heuristic
from ci_bootstrap.contracts import Classification, RepoSnapshot
from ci_bootstrap.cookbooks.base import PUSH_GUARD, SONAR_GUARD, phase_labels
from ci_bootstrap.generate import UnsupportedError, generate


def _snap(*paths: str, name: str = "demo", branch: str = "main") -> RepoSnapshot:
    return RepoSnapshot(
        repo_url=f"https://github.com/x/{name}", owner="x", name=name,
        default_branch=branch, tree=list(paths),
    )


def _classification(build_system: str) -> Classification:
    return Classification(
        language="x", build_system=build_system, test_command="t",
        confidence=1.0, method="test",
    )


# --- registry ------------------------------------------------------------

def test_registry_has_java_and_dotnet():
    assert set(cookbooks.supported()) >= {"maven", "dotnet"}


# --- structure of the generated workflow ---------------------------------

@pytest.mark.parametrize("build_system", ["maven", "dotnet"])
def test_workflow_is_valid_yaml_with_all_four_phases(build_system):
    wf = generate(_classification(build_system), _snap("pom.xml"))
    data = yaml.safe_load(wf.content)

    # `on:` survives as a string key, not the YAML boolean True footgun.
    assert "on" in data and True not in data
    assert "pull_request" in data["on"] and "push" in data["on"]
    assert data["permissions"] == {"contents": "read", "packages": "write"}
    assert list(data["jobs"]) == ["ci"]

    # All four phases present as named steps.
    assert phase_labels(wf.content) == {"build", "test", "sonar", "push"}


@pytest.mark.parametrize("build_system", ["maven", "dotnet"])
def test_phases_appear_in_order(build_system):
    data = yaml.safe_load(generate(_classification(build_system), _snap()).content)
    names = [s.get("name", "").lower() for s in data["jobs"]["ci"]["steps"]]
    positions = {p: next(i for i, n in enumerate(names) if p in n) for p in ("build", "test", "sonar", "push")}
    assert positions["build"] < positions["test"] < positions["sonar"] < positions["push"]


@pytest.mark.parametrize("build_system", ["maven", "dotnet"])
def test_sonar_and_push_are_guarded(build_system):
    steps = yaml.safe_load(generate(_classification(build_system), _snap()).content)["jobs"]["ci"]["steps"]
    for s in steps:
        name = s.get("name", "").lower()
        if "sonar" in name:
            assert s.get("if") == SONAR_GUARD
            assert s.get("env", {}).get("SONAR_TOKEN") == "${{ secrets.SONAR_TOKEN }}"
        if "push" in name:
            assert s.get("if") == PUSH_GUARD


def test_default_dockerfile_written_only_when_absent():
    with_df = generate(_classification("maven"), _snap("pom.xml", "Dockerfile")).content
    without_df = generate(_classification("maven"), _snap("pom.xml")).content
    assert "Write default Dockerfile" not in with_df
    assert "Write default Dockerfile" in without_df


@pytest.mark.parametrize("build_system", ["maven", "dotnet"])
def test_sonar_org_is_lowercased_and_project_key_preserves_case(build_system):
    snap = RepoSnapshot(
        repo_url="https://github.com/Komali612/java-service", owner="Komali612",
        name="java-service", default_branch="main", tree=["pom.xml"],
    )
    wf = generate(_classification(build_system), snap).content
    assert "__SONAR_ORG__" not in wf and "__SONAR_PROJECT_KEY__" not in wf  # placeholders filled
    assert "komali612" in wf                       # org is lowercased (SonarCloud convention)
    assert "Komali612_java-service" in wf          # project key keeps original case
    assert "organization=Komali612" not in wf and 'o:"Komali612"' not in wf  # not the wrong case


def test_push_targets_ghcr_with_lowercase_image():
    wf = generate(_classification("dotnet"), _snap()).content
    assert "ghcr.io/x/demo:${{ github.sha }}" in wf
    # Must NOT use ${{ github.repository }}: it preserves owner case, and GHCR
    # rejects uppercase image paths ("repository name must be lowercase").
    assert "${{ github.repository }}" not in wf


def test_image_tag_is_lowercased_for_uppercase_owner():
    # Regression: an owner/repo with uppercase letters must still yield a valid,
    # lowercase GHCR tag -- this is the bug that failed python-service's push.
    snap = RepoSnapshot(
        repo_url="https://github.com/Komali612/Python-Service", owner="Komali612",
        name="Python-Service", default_branch="main", tree=[],
    )
    wf = generate(_classification("dotnet"), snap).content
    assert "ghcr.io/komali612/python-service:${{ github.sha }}" in wf
    assert "ghcr.io/Komali612" not in wf and "__IMAGE__" not in wf


def test_default_branch_flows_into_push_trigger():
    data = yaml.safe_load(generate(_classification("maven"), _snap(branch="release")).content)
    assert data["on"]["push"]["branches"] == ["release"]


# --- the unsupported path ------------------------------------------------

def test_generate_raises_for_unknown_build_system():
    with pytest.raises(UnsupportedError) as exc:
        generate(_classification("cargo"), _snap("Cargo.toml"))
    assert "cargo" in str(exc.value)
    assert "maven" in str(exc.value)  # error lists what IS supported


# --- heuristic classifier feeds the right cookbook key -------------------

@pytest.mark.parametrize(
    "paths,build_system",
    [(["pom.xml"], "maven"), (["src/App.csproj", "App.sln"], "dotnet")],
)
def test_heuristic_keys_match_cookbooks(paths, build_system):
    c = classify_with_heuristic(_snap(*paths))
    assert c.build_system == build_system
    assert cookbooks.get(c.build_system) is not None  # heuristic result is generatable
