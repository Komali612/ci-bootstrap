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
    """The CI workflow a cookbook produced. Deterministic, so always valid."""

    path: str  # e.g. ".github/workflows/ci.yml"
    content: str
    cookbook: str  # which cookbook produced it, e.g. "maven"
    phases: list[str] = ["build", "test", "sonar", "push"]  # always all four


class BootstrapResult(BaseModel):
    """The service's final answer, returned by the HTTP endpoint and the CLI."""

    repo_url: str
    status: str  # "opened" | "generated" | "error"
    classification: Classification | None = None
    workflow: GeneratedWorkflow | None = None
    branch: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    message: str = ""
