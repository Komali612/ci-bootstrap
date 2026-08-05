"""Data contracts passed between the service's stages.

The flow is deliberately linear:

    RepoSnapshot  ->  Classification  ->  GeneratedWorkflow  ->  BootstrapResult
      (ingest)         (classify, LLM)      (generate, cookbook)     (github)

Language/ecosystem are free-form strings the LLM fills in; the *generator* is
what constrains us to what we actually support (it raises if no cookbook matches
the classification).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RepoSnapshot(BaseModel):
    """A compact, LLM-friendly view of the repository under inspection."""

    repo_url: str
    owner: str
    name: str
    default_branch: str
    tree: list[str] = []  # repo-relative file paths (capped)
    manifests: dict[str, str] = {}  # path -> (truncated) contents of key manifest files


class LLMClassification(BaseModel):
    """Structured output we ask the classification LLM to produce."""

    language: str = Field(description="Primary language, lowercase, e.g. java, csharp, python, go")
    build_system: str = Field(description="Build tool / package manager actually used, e.g. maven, gradle, dotnet, pip, npm")
    test_command: str = Field(description="The shell command that runs this project's tests, e.g. 'mvn -B verify'")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(description="Files/facts that support the classification")


class LLMCookbook(BaseModel):
    """Structured output for the LLM fallback: ONLY the fields a cookbook varies.

    The LLM never writes the workflow YAML. It fills in the same slots a normal
    cookbook supplies; the deterministic skeleton assembles the four phases and
    guards around them, exactly as for a built-in cookbook.
    """

    language: str = Field(description="Primary language, lowercase (e.g. elixir, scala, haskell)")
    setup_steps_yaml: str = Field(
        description="A YAML sequence of GitHub Actions steps (after checkout) that install the "
        "toolchain, e.g. an actions/setup-* step with a version. Just the steps, as a YAML list."
    )
    build: list[str] = Field(description="Shell commands for the Build phase (install deps / compile)")
    test: list[str] = Field(description="Shell commands for the Test phase")
    sonar_strategy: str = Field(
        description="Which Sonar scanner to use: one of 'maven', 'dotnet', or 'generic'. "
        "Use 'generic' (the stack-agnostic CLI scanner) unless the build tool has a first-class one."
    )
    dockerfile: str = Field(description="A minimal, stack-appropriate multi-stage Dockerfile")


class Classification(BaseModel):
    """Handoff contract: classify -> generate."""

    language: str
    build_system: str  # this is the key the cookbook registry is keyed on
    test_command: str
    confidence: float
    method: str  # "llm" | "heuristic"
    evidence: list[str] = []
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None


class GeneratedWorkflow(BaseModel):
    """The CI workflow a cookbook produced. The skeleton is deterministic even
    when the cookbook's fill-ins came from the LLM fallback."""

    path: str  # e.g. ".github/workflows/app-ci.yml"
    content: str
    cookbook: str  # which cookbook produced it, e.g. "maven"
    phases: list[str] = ["build", "test", "sonar", "push"]  # always all four
    llm_authored: bool = False  # True when the cookbook fields were LLM-generated (no built-in cookbook)
    llm_input_tokens: int | None = None
    llm_output_tokens: int | None = None


class BootstrapResult(BaseModel):
    """The service's final answer, returned by the HTTP endpoint and the CLI."""

    repo_url: str
    status: str  # "opened" | "generated" | "error"
    kind: str = "ci"  # "ci" (bootstrap) | "cd" (add_cd) — which pipeline this run produced
    classification: Classification | None = None
    workflow: GeneratedWorkflow | None = None
    branch: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    sonar_secret_set: bool | None = None  # True/False if we tried to write SONAR_TOKEN; None if not configured
    sonar_project: str | None = None       # "created" | "exists" | "error" | None (SonarCloud project provisioning)
    cd_gate: str | None = None             # CD only: how production is gated ("automatic" | "manual approval ...")
    merged: bool = False                   # True if we auto-merged the PR we opened
    merge_sha: str | None = None           # the resulting commit SHA on the base branch, when merged
    message: str = ""


class ChainResult(BaseModel):
    """The full CI -> image -> CD chain, driven from one 'Run CI agent' click."""

    repo_url: str
    ci: BootstrapResult                    # the CI run (its .merged/.merge_sha say if/where it merged)
    image_ready: bool = False              # True once CI succeeded on main and pushed an image
    cd: BootstrapResult | None = None      # the CD run (None if we stopped before it)
    message: str = ""
