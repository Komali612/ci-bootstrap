---
name: bootstrap-ci
description: >-
  Add a complete CI pipeline to a GitHub repository given only its URL. Use this
  whenever the user wants to bootstrap CI, "add CI to <repo>", set up a GitHub
  Actions workflow, generate a ci.yml, or wire up build/test/sonar/push for a
  repository — even if they only paste a repo URL and say "set this up" without
  naming GitHub Actions. The skill clones the repo, classifies its language and
  build system, generates a fixed four-phase workflow (build → test → sonar →
  push) from a matching cookbook, and opens a pull request adding
  .github/workflows/ci.yml. Trigger it for any "give a repo continuous
  integration / a CI workflow / a pipeline" request.
---

# bootstrap-ci

Give a GitHub repository a CI pipeline. The flow is deliberately linear and the
same every time:

```
repo_url → clone → classify (language + build system) → pick cookbook → render ci.yml → open PR → PR number
```

This skill is the "do it by hand" counterpart to the cicd-bootstrap **service**.
The service is a Python program that calls the Anthropic API to classify and
then renders YAML from code. Here **you are the classifier** — you read the
repo's manifests and decide — and the cookbooks are reference files you render
from. Same contract, no service to run and no API key needed.

## The rules that never change

These are structural, not options. Do not offer the user a menu of phases or
ask which ones they want — every CI file this skill produces has the **same four
phases, in this order**:

1. **Build** — install dependencies / compile.
2. **Test** — run the project's tests.
3. **Sonar** — run a SonarCloud scan. Skipped automatically until a `SONAR_TOKEN`
   secret exists (so it never fails a repo that hasn't wired up Sonar yet).
4. **Push** — build a Docker image and push it to GHCR. Runs **only** on a push
   to the default branch, never on pull requests.

The four-phase structure and those two guards live in one place —
[references/skeleton.md](references/skeleton.md) — and every cookbook obeys it.
A cookbook only supplies the *language-specific fill-ins* (toolchain setup,
build/test commands, a Sonar strategy, a default Dockerfile); it can never add,
drop, or reorder phases. Those fill-ins live as data in
[references/cookbooks.yaml](references/cookbooks.yaml) — the **same file the
cicd-bootstrap service reads**, so the skill and the service can't drift.

**If there is no cookbook for the repo's build system, stop and report an
error.** Do not improvise a workflow or write YAML from scratch — an honest
"unsupported: <build system>" is the correct outcome. This keeps every emitted
file reproducible and reviewable.

## Steps

### 1. Get the repo URL and clone it

Take the GitHub repo URL from the user. Assume you have access. Shallow-clone it
into a scratch directory:

```bash
git clone --depth 1 <repo_url> <scratch>/repo
```

If the clone fails (private repo you can't reach, bad URL, network), **stop and
report the error to the user** — do not guess at the repo's contents.

After cloning, note the **owner**, **repo name**, and **default branch**:

```bash
git -C <scratch>/repo remote get-url origin        # owner/name
git -C <scratch>/repo symbolic-ref --short HEAD     # default branch (e.g. main)
```

### 2. Classify: language + build system

Read the file tree and the contents of any manifest files (`pom.xml`,
`*.csproj`/`*.sln`, `pyproject.toml`/`requirements.txt`, `go.mod`,
`package.json`, `Cargo.toml`, `build.gradle`, …). From those, decide the
**build system** — this is the key that selects the cookbook. Prefer signals
from manifest *contents* over file extensions.

Quick signal → build-system map (the manifest is the giveaway):

| Signal in the repo | build_system | language |
|---|---|---|
| `pom.xml` | `maven` | java |
| `*.csproj` / `*.sln` / `*.fsproj` | `dotnet` | csharp |
| `pyproject.toml` / `requirements.txt` / `setup.py` | `pip` | python |
| `go.mod` | `go` | go |

This is exactly the `build_system` field the service's classifier produces —
you are doing the same job with your own judgement instead of an API call. If
the repo is genuinely ambiguous, say so and ask the user rather than guessing.

### 3. Select the cookbook

Open [references/cookbooks.yaml](references/cookbooks.yaml) and look up the
`build_system` under its `cookbooks:` section. The keys present there are the
supported build systems (currently `maven`, `dotnet`, `pip`, `go`).

**No entry for the build system → stop.** Tell the user it's unsupported and
list the keys that *are* present. Do not fall back to writing a workflow
yourself — an honest "unsupported: <build system>" is the correct outcome.
(Adding support is a one-line-block change — see *Extending* below.)

### 4. Assemble and write `.github/workflows/ci.yml`

Read [references/skeleton.md](references/skeleton.md) and assemble the workflow
from the cookbook entry: the fixed skeleton + the entry's setup / build / test /
Sonar-strategy / Dockerfile, with the Sonar and Push guards applied. Then fill
the three placeholders:

- `__SONAR_ORG__` → the repo **owner, lowercased**.
- `__SONAR_PROJECT_KEY__` → `<owner>_<name>` (owner's original case).
- `__DEFAULT_BRANCH__` → the default branch from step 1.

Write the result to `.github/workflows/ci.yml` in the clone. **If that file
already exists, do not overwrite it** — write `.github/workflows/cicd-bootstrap.yml`
instead and mention this to the user.

Then validate it — this is the safety net that keeps your assembly honest:

```bash
python3 - "$WF" <<'PY'
import sys, yaml
data = yaml.safe_load(open(sys.argv[1]))
steps = data["jobs"]["ci"]["steps"]
names = " ".join(str(s.get("name","")).lower() for s in steps)
missing = [p for p in ("build","test","sonar","push") if p not in names]
assert not missing, f"missing phases: {missing}"
assert data.get("permissions") == {"contents":"read","packages":"write"}
print("ci.yml OK — all four phases present, permissions correct")
PY
```

If validation fails, re-read `skeleton.md` and fix the assembly — never hand-wave
the structure to make it pass.

### 5. Open the pull request

Commit the workflow on a fresh branch and open a PR with the `gh` CLI (the
user's `gh` is authenticated). Assume you can push to the repo; if the push or
PR fails because you lack access, **report the error and stop** — this skill
does not fork.

```bash
cd <scratch>/repo
git checkout -b cicd-bootstrap/add-ci
git add .github/workflows/ci.yml
git -c user.name="cicd-bootstrap" -c user.email="cicd-bootstrap@users.noreply.github.com" \
    commit -m "ci: add four-phase CI workflow (via bootstrap-ci)"
git push -u origin cicd-bootstrap/add-ci
gh pr create \
  --base "<default_branch>" --head "cicd-bootstrap/add-ci" \
  --title "ci: add CI workflow (via bootstrap-ci)" \
  --body "Adds a four-phase CI workflow (build → test → sonar → push), generated from the **<build_system>** cookbook after classifying this repo as **<language>**. Sonar is skipped until a SONAR_TOKEN secret is set; the image push runs only on merges to <default_branch>. Review before merging."
```

Report back the **PR number and URL** (`gh pr create` prints the URL), plus a
one-line summary: what you classified the repo as, which cookbook you used, and
the reminder that Sonar/Push stay dormant until their secrets/registry are set
up.

## Extending: adding a new language / build system

This is the whole point of the cookbook design — it should be a one-block change:

1. Add an entry under `cookbooks:` in
   [references/cookbooks.yaml](references/cookbooks.yaml): its `language`,
   `setup` steps, `build`/`test` commands, a `sonar` strategy name (usually
   `generic`), and a `dockerfile`. Only add a `sonar_strategies:` entry if none
   of the three existing scanners fit — which is rare.
2. Keep the same file in sync with the service's copy at
   `src/cicd_bootstrap/cookbooks/cookbooks.yaml` (a test asserts they match).

Nothing else changes — not this SKILL.md, not the skeleton. If you find yourself
editing the *workflow* to support a new language, something has gone wrong: the
per-language knowledge belongs entirely in `cookbooks.yaml`.

## Reference files

- [references/cookbooks.yaml](references/cookbooks.yaml) — the per-language data
  (setup, build, test, Sonar strategy, Dockerfile). The same file the service
  reads. Read this to find the cookbook for a build system.
- [references/skeleton.md](references/skeleton.md) — how to assemble a full
  workflow from a cookbook entry: the fixed skeleton, the Sonar/Push guards, and
  the placeholders. Read this every time you generate, and when adding a cookbook.
