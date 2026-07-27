"""The cookbook engine: one fixed 4-phase skeleton + a registry loaded from data.

The four phases -- Build, Test, Sonar, Push -- are defined *here*, once, and are
always emitted. A cookbook does not get to add, remove, or reorder phases; it
only supplies the language-specific fill-ins (toolchain setup, the build/test
commands, which Sonar strategy to use, and a default Dockerfile).

Those fill-ins are not hard-coded per language anymore -- they are read from
``cookbooks.yaml`` (the single source of truth, shared with the bootstrap-ci
skill). Adding a language therefore means editing that data file; nothing in
this module changes. That is the whole extensibility story.

The guards on Sonar (skip unless SONAR_TOKEN is set) and Push (only on a push to
the default branch) are structural: always present, never user-selectable. They
exist so the generated workflow doesn't spuriously fail before its
secrets/registry are wired up.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..contracts import RepoSnapshot

Step = dict[str, Any]

# Structural guards -- fixed, not configurable.
SONAR_GUARD = "${{ env.SONAR_TOKEN != '' }}"
PUSH_GUARD = "github.event_name == 'push'"

REQUIRED_PHASES = ("build", "test", "sonar", "push")

# The shared data file. Both the service (this module) and the skill read it.
DATA_PATH = Path(__file__).with_name("cookbooks.yaml")


@dataclass(frozen=True)
class Cookbook:
    """Everything language-specific needed to fill the 4-phase skeleton.

    Instances are built from ``cookbooks.yaml`` at import time; you should not
    need to construct one by hand.
    """

    key: str            # registry key = build system, e.g. "maven", "dotnet"
    language: str       # e.g. "java", "csharp"
    display_name: str   # e.g. "Java (Maven)"
    setup: list[Step]   # steps after checkout that install the toolchain
    build: list[str]    # Build-phase shell commands
    test: list[str]     # Test-phase shell commands
    sonar: list[Step]   # Sonar-phase steps (from the chosen strategy); names contain "Sonar"
    default_dockerfile: str  # written before the image build only if the repo has no Dockerfile


# --- registry ------------------------------------------------------------

_REGISTRY: dict[str, Cookbook] = {}


def register(cookbook: Cookbook) -> None:
    _REGISTRY[cookbook.key] = cookbook


def get(build_system: str) -> Cookbook | None:
    return _REGISTRY.get(build_system.lower().strip())


def supported() -> list[str]:
    return sorted(_REGISTRY)


# --- loading cookbooks.yaml ----------------------------------------------

def _as_lines(value: str | list[str]) -> list[str]:
    """A command block may be a single (possibly multi-line) string or a list."""
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def load(path: Path = DATA_PATH) -> None:
    """Populate the registry from the data file. Called once at import."""
    raw = yaml.safe_load(path.read_text())
    strategies: dict[str, list[Step]] = raw.get("sonar_strategies", {})

    for key, spec in raw.get("cookbooks", {}).items():
        strategy_name = spec.get("sonar", "generic")
        if strategy_name not in strategies:
            raise ValueError(
                f"cookbook {key!r} references unknown sonar strategy "
                f"{strategy_name!r} (have: {', '.join(sorted(strategies))})"
            )
        register(Cookbook(
            key=key,
            language=spec["language"],
            display_name=spec.get("display_name", spec["language"]),
            setup=[dict(s) for s in spec.get("setup", [])],
            build=_as_lines(spec["build"]),
            test=_as_lines(spec["test"]),
            sonar=[dict(s) for s in strategies[strategy_name]],
            default_dockerfile=spec["dockerfile"],
        ))


# --- workflow assembly ---------------------------------------------------

def render_workflow(cookbook: Cookbook, snapshot: RepoSnapshot) -> str:
    """Assemble the full 4-phase workflow YAML for `cookbook` against `snapshot`."""
    steps: list[Step] = [{"name": "Checkout", "uses": "actions/checkout@v4"}]
    steps += cookbook.setup
    steps.append({"name": "Build", "run": _script(cookbook.build)})
    steps.append({"name": "Test", "run": _script(cookbook.test)})
    steps += _sonar_phase(cookbook)
    steps += _push_phase(cookbook, snapshot)

    workflow = {
        "name": "CI",
        "on": {
            "push": {"branches": [snapshot.default_branch]},
            "pull_request": None,
            "workflow_dispatch": None,
        },
        "permissions": {"contents": "read", "packages": "write"},
        "jobs": {"ci": {"runs-on": "ubuntu-latest", "steps": steps}},
    }
    return _fill_placeholders(_dump(workflow), snapshot)


# Cookbooks reference these placeholders; we fill them in at generation time from
# the snapshot so the emitted YAML is concrete and readable. SonarCloud org keys
# are lowercase (its convention for GitHub-imported orgs), while project keys keep
# the owner's original case -- deriving them from ${{ github.* }} at runtime gets
# the org-key case wrong, which is a hard error.
SONAR_ORG_PLACEHOLDER = "__SONAR_ORG__"
SONAR_PROJECT_KEY_PLACEHOLDER = "__SONAR_PROJECT_KEY__"


def _fill_placeholders(text: str, snapshot: RepoSnapshot) -> str:
    text = text.replace(SONAR_ORG_PLACEHOLDER, snapshot.owner.lower())
    text = text.replace(SONAR_PROJECT_KEY_PLACEHOLDER, f"{snapshot.owner}_{snapshot.name}")
    return text


def _sonar_phase(cookbook: Cookbook) -> list[Step]:
    """Guard each Sonar step so it is skipped when SONAR_TOKEN is absent."""
    guarded: list[Step] = []
    for step in cookbook.sonar:
        s: Step = {"name": step.get("name", "Sonar scan")}
        s["if"] = SONAR_GUARD
        # Merge the token into the step env without dropping the strategy's own.
        env = {"SONAR_TOKEN": "${{ secrets.SONAR_TOKEN }}", "GITHUB_TOKEN": "${{ secrets.GITHUB_TOKEN }}"}
        env.update(step.get("env", {}))
        s["env"] = env
        for k, v in step.items():
            if k not in ("name", "if", "env"):
                s[k] = v
        guarded.append(s)
    return guarded


def _push_phase(cookbook: Cookbook, snapshot: RepoSnapshot) -> list[Step]:
    """Log in to GHCR and push an image, only on a push to the default branch."""
    steps: list[Step] = []
    if not _has_dockerfile(snapshot):
        steps.append({
            "name": "Write default Dockerfile (Push)",
            "if": PUSH_GUARD,
            "run": _heredoc("Dockerfile", cookbook.default_dockerfile),
        })
    steps.append({
        "name": "Log in to GHCR (Push)",
        "if": PUSH_GUARD,
        "uses": "docker/login-action@v3",
        "with": {
            "registry": "ghcr.io",
            "username": "${{ github.actor }}",
            "password": "${{ secrets.GITHUB_TOKEN }}",
        },
    })
    steps.append({
        "name": "Build and push image (Push)",
        "if": PUSH_GUARD,
        "uses": "docker/build-push-action@v6",
        "with": {
            "context": ".",
            "push": True,
            "tags": "ghcr.io/${{ github.repository }}:${{ github.sha }}",
        },
    })
    return steps


def _has_dockerfile(snapshot: RepoSnapshot) -> bool:
    return any(Path(p).name == "Dockerfile" for p in snapshot.tree)


def _script(commands: list[str]) -> str:
    return "\n".join(commands)


def _heredoc(filename: str, content: str) -> str:
    # Quoted heredoc so nothing in the Dockerfile is shell-expanded.
    return f"cat > {filename} <<'DOCKERFILE'\n{content.strip()}\nDOCKERFILE"


# --- YAML dumping --------------------------------------------------------

class _WorkflowDumper(yaml.SafeDumper):
    """A dumper that keeps key order and renders multi-line strings as block scalars."""


def _str_representer(dumper: yaml.Dumper, data: str):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_WorkflowDumper.add_representer(str, _str_representer)


def _dump(workflow: dict) -> str:
    text = yaml.dump(
        workflow, Dumper=_WorkflowDumper,
        sort_keys=False, default_flow_style=False, width=4096,  # keep commands on one line
    )
    return "# Generated by ci-bootstrap. Review before merging.\n" + text


def phase_labels(workflow_yaml: str) -> set[str]:
    """Which of the required phases are present as named steps? (used by tests)"""
    data = yaml.safe_load(workflow_yaml)
    names = " ".join(
        str(step.get("name", "")).lower()
        for job in data.get("jobs", {}).values()
        for step in job.get("steps", [])
    )
    return {p for p in REQUIRED_PHASES if p in names}


# Populate the registry from the data file on import.
load()
