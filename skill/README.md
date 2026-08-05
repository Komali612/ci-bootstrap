# `bootstrap-ci` — the skill (a second way to do the same thing)

This folder is a **Claude Code skill** that performs the same job as the
`cicd-bootstrap` service in the repo root, by a different mechanism.

| | The service (`src/cicd_bootstrap/`) | The skill (`bootstrap-ci/`) |
|---|---|---|
| What runs it | A Python program (FastAPI / CLI) | Claude Code, following `SKILL.md` |
| Who classifies | An **Anthropic API call** (Haiku, structured output) | **Claude itself** reads the manifests and decides |
| How the YAML is made | reads `cookbooks.yaml`, renders in code | reads the **same** `cookbooks.yaml`, Claude assembles it |
| How a PR opens | `httpx` against the GitHub REST API | the `gh` CLI |
| Needs an API key | Yes (to classify) | No |

Both share the **same contract** *and the same data*: clone → classify
(language + build system) → render a fixed **four-phase** workflow (build → test
→ sonar → push) from a cookbook keyed on the build system → open a PR. Neither
ever lets an LLM free-write the workflow, and both **error out** on a build
system that has no cookbook.

The per-language content lives once in **`cookbooks.yaml`** (setup, build/test
commands, Sonar strategy, Dockerfile). The service reads its copy at
`src/cicd_bootstrap/cookbooks/cookbooks.yaml`; the skill reads the copy under
`references/`. A test in the service repo asserts the two are identical, so they
can't drift. The fixed scaffolding (header, guards, push phase) lives in the
*generator* — `base.py` for the service, `references/skeleton.md` for the skill.

## Layout

```
bootstrap-ci/
├── SKILL.md                     the procedure Claude follows
└── references/
    ├── cookbooks.yaml           per-language data (shared with the service)
    └── skeleton.md              how to assemble a workflow from a cookbook entry
```

## Using it

Copy (or symlink) `bootstrap-ci/` into a skills directory Claude Code loads —
`~/.claude/skills/` (personal) or `<project>/.claude/skills/` (project) — then
just ask, e.g. *"add CI to https://github.com/owner/repo"*.

## Extending it

Add one file under `references/cookbooks/` for the new build system and add a row
to the two tables in `SKILL.md` (step 3). Nothing else changes — see
`references/skeleton.md` for the contract a cookbook must satisfy.
