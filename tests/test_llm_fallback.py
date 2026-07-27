"""Offline tests for the optional LLM cookbook fallback.

We never call the real LLM here. We check two things:

1. The *policy*: without the fallback, an unsupported stack still raises; with
   it, generate() routes through the author and marks the result.
2. The *invariant that matters*: even when the cookbook fields come from the LLM,
   the deterministic skeleton still yields all four phases with both guards. The
   LLM only fills setup/build/test/sonar-strategy/Dockerfile.
"""

from __future__ import annotations

import pytest
import yaml

from ci_bootstrap import author, cookbooks
from ci_bootstrap.cookbooks.base import PUSH_GUARD, SONAR_GUARD, Cookbook, phase_labels
from ci_bootstrap.contracts import Classification, RepoSnapshot
from ci_bootstrap.generate import UnsupportedError, generate


def _snap(*paths: str, name: str = "demo") -> RepoSnapshot:
    return RepoSnapshot(
        repo_url=f"https://github.com/Komali612/{name}", owner="Komali612",
        name=name, default_branch="main", tree=list(paths),
    )


def _cls(build_system: str) -> Classification:
    return Classification(language="elixir", build_system=build_system,
                          test_command="mix test", confidence=1.0, method="test")


def test_unsupported_without_fallback_still_raises():
    with pytest.raises(UnsupportedError):
        generate(_cls("mix"), _snap("mix.exs"))


def test_parse_setup_accepts_a_step_list_and_rejects_garbage():
    steps = author._parse_setup("- name: Set up\n  uses: actions/setup-x@v1\n")
    assert steps == [{"name": "Set up", "uses": "actions/setup-x@v1"}]
    assert author._parse_setup("") == []            # empty is fine (no setup)
    with pytest.raises(author.AuthorError):
        author._parse_setup("not a list")           # a scalar, not step mappings
    with pytest.raises(author.AuthorError):
        author._parse_setup("- ok\n- also just a string")  # list, but not of mappings


def test_fallback_routes_through_author_and_assembles_four_phases(monkeypatch):
    # Simulate what the LLM would produce (an unregistered cookbook for "mix").
    fake = Cookbook(
        key="mix", language="elixir", display_name="mix (LLM-authored)",
        setup=[{
            "name": "Set up Elixir", "uses": "erlef/setup-beam@v1",
            "with": {"otp-version": "26", "elixir-version": "1.16"},
        }],
        build=["mix deps.get", "mix compile"],
        test=["mix test"],
        sonar=cookbooks.sonar_strategy("generic"),  # the LLM picks a real strategy
        default_dockerfile="FROM elixir:1.16\nWORKDIR /app\nCOPY . .\nEXPOSE 8080\n",
    )
    monkeypatch.setattr(author, "author_cookbook",
                        lambda snap, cls: (fake, {"input_tokens": 11, "output_tokens": 22}))

    wf = generate(_cls("mix"), _snap("mix.exs"), allow_llm_fallback=True)

    assert wf.llm_authored is True
    assert wf.cookbook == "mix"
    assert (wf.llm_input_tokens, wf.llm_output_tokens) == (11, 22)

    data = yaml.safe_load(wf.content)
    assert phase_labels(wf.content) == {"build", "test", "sonar", "push"}
    assert "erlef/setup-beam@v1" in wf.content  # the LLM's setup step is in the workflow

    # The guards are unchanged even though the cookbook came from the LLM.
    for s in data["jobs"]["ci"]["steps"]:
        name = str(s.get("name", "")).lower()
        if "sonar" in name:
            assert s.get("if") == SONAR_GUARD
        if "push" in name:
            assert s.get("if") == PUSH_GUARD
