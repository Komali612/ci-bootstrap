"""Classification stage: ask an LLM what language and build system the repo uses.

The LLM is advisory. If it is confident we take its answer; otherwise (or if no
API key is set) we fall back to a small deterministic heuristic over the
manifest filenames. Either way the output is a `Classification` whose
`build_system` is the key the generator looks a cookbook up by.
"""

from __future__ import annotations

import os
from pathlib import Path

from .contracts import Classification, LLMClassification, RepoSnapshot

CONFIDENCE_THRESHOLD = 0.8
DEFAULT_MODEL = "claude-haiku-4-5"  # classification is the cheap LLM use case

SYSTEM_PROMPT = """You are a build-systems expert classifying a source repository.

You are given the repository's file tree and the contents of its manifest
files. Determine:
- language: the primary programming language, lowercase (e.g. java, csharp, python, go, javascript).
- build_system: the build tool or package manager the project ACTUALLY uses
  (e.g. maven, gradle, dotnet, pip, poetry, npm, yarn, go, cargo). This is the
  most important field -- base it on the manifests present (pom.xml -> maven,
  *.csproj/*.sln -> dotnet, etc.), not on guesses.
- test_command: the single shell command a contributor runs to execute this
  project's tests (e.g. "mvn -B verify", "dotnet test", "pytest").
- confidence: 0..1, honest about ambiguity.
- evidence: concrete files or facts that justify the call.

Prefer signals from manifest contents over file extensions."""


def classify(snapshot: RepoSnapshot) -> Classification:
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            llm, usage = _classify_with_llm(snapshot)
            if llm.confidence >= CONFIDENCE_THRESHOLD:
                return Classification(
                    language=llm.language.lower().strip(),
                    build_system=llm.build_system.lower().strip(),
                    test_command=llm.test_command.strip(),
                    confidence=llm.confidence,
                    method="llm",
                    evidence=llm.evidence,
                    llm_input_tokens=usage.get("input_tokens"),
                    llm_output_tokens=usage.get("output_tokens"),
                )
            print(
                f"[classify] LLM confidence {llm.confidence:.2f} below threshold "
                f"{CONFIDENCE_THRESHOLD}; falling back to heuristic"
            )
        except Exception as exc:
            print(f"[classify] LLM classification failed ({exc}); using heuristic")
    else:
        print("[classify] ANTHROPIC_API_KEY not set; using heuristic fallback")

    return classify_with_heuristic(snapshot)


def _render(snapshot: RepoSnapshot) -> str:
    lines = ["# File tree", *snapshot.tree, "", "# Manifest files"]
    if snapshot.manifests:
        for path, content in snapshot.manifests.items():
            lines += [f"\n## {path}", "```", content, "```"]
    else:
        lines.append("(none found)")
    return "\n".join(lines)


def _classify_with_llm(snapshot: RepoSnapshot) -> tuple[LLMClassification, dict]:
    import anthropic

    client = anthropic.Anthropic().with_options(timeout=60.0, max_retries=1)
    response = client.messages.parse(
        model=os.environ.get("CLASSIFIER_MODEL", DEFAULT_MODEL),
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _render(snapshot)}],
        output_format=LLMClassification,
    )
    parsed = response.parsed_output
    if parsed is None:
        raise ValueError("LLM returned no parseable classification")
    usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
    return parsed, usage


# (manifest signal, language, build_system, test_command), in priority order.
_HEURISTICS: list[tuple[str, str, str, str]] = [
    ("pom.xml", "java", "maven", "mvn -B verify"),
    ("build.gradle", "java", "gradle", "./gradlew test"),
    ("build.gradle.kts", "java", "gradle", "./gradlew test"),
    ("pyproject.toml", "python", "pip", "pytest"),
    ("requirements.txt", "python", "pip", "pytest"),
    ("package.json", "javascript", "npm", "npm test"),
    ("go.mod", "go", "go", "go test ./..."),
    ("Cargo.toml", "rust", "cargo", "cargo test"),
]


def classify_with_heuristic(snapshot: RepoSnapshot) -> Classification:
    names = {Path(p).name for p in snapshot.tree}
    if any(n.endswith((".csproj", ".fsproj", ".sln")) for n in names):
        return Classification(
            language="csharp", build_system="dotnet", test_command="dotnet test",
            confidence=0.9, method="heuristic",
            evidence=[p for p in snapshot.tree if p.endswith((".csproj", ".sln", ".fsproj"))][:5],
        )
    for signal, language, build_system, test_cmd in _HEURISTICS:
        if signal in names:
            return Classification(
                language=language, build_system=build_system, test_command=test_cmd,
                confidence=0.9, method="heuristic", evidence=[signal],
            )
    raise ValueError(
        "could not classify the repository from its manifests; "
        f"top-level files seen: {sorted(names)[:20]}"
    )
