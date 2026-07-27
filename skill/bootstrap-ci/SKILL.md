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

This skill is the "do it by hand" counterpart to the ci-bootstrap **service**.
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
A cookbook only supplies the *language-specific fill-ins*; it can never add,
drop, or reorder phases.

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

Map the `build_system` to a cookbook file in
[references/cookbooks/](references/cookbooks/):

| build_system | cookbook |
|---|---|
| `maven` | [references/cookbooks/maven.md](references/cookbooks/maven.md) |
| `dotnet` | [references/cookbooks/dotnet.md](references/cookbooks/dotnet.md) |
| `pip` | [references/cookbooks/pip.md](references/cookbooks/pip.md) |
| `go` | [references/cookbooks/go.md](references/cookbooks/go.md) |

**No matching cookbook → stop.** Tell the user the build system is unsupported
and list the ones that are (the filenames above). Do not fall back to writing a
workflow yourself. (Adding support is a one-file change — see *Extending* below.)

### 4. Render `.github/workflows/ci.yml`

Open the chosen cookbook file. It contains a **complete, ready ci.yml** already
laid out with the four phases. Produce the final file by making exactly these
substitutions:

- Replace `__SONAR_ORG__` with the repo **owner, lowercased** (SonarCloud
  lowercases org keys for GitHub-imported orgs).
- Replace `__SONAR_PROJECT_KEY__` with `<owner>_<name>` (keep the owner's
  original case — this is the SonarCloud project key convention).
- Replace `__DEFAULT_BRANCH__` with the default branch you found in step 1.

Write the result to `.github/workflows/ci.yml` in the clone. **If that file
already exists, do not overwrite it** — write to `.github/workflows/ci-bootstrap.yml`
instead and mention this to the user.

Then sanity-check that it parses (cheap insurance, since the template is
known-good):

```bash
python3 -c "import yaml,sys; yaml.safe_load(open(sys.argv[1])); print('ci.yml OK')" <scratch>/repo/.github/workflows/ci.yml
```

Do not hand-edit the phase structure. If something looks wrong, the fix belongs
in the cookbook, not in this one output.

### 5. Open the pull request

Commit the workflow on a fresh branch and open a PR with the `gh` CLI (the
user's `gh` is authenticated). Assume you can push to the repo; if the push or
PR fails because you lack access, **report the error and stop** — this skill
does not fork.

```bash
cd <scratch>/repo
git checkout -b ci-bootstrap/add-ci
git add .github/workflows/ci.yml
git -c user.name="ci-bootstrap" -c user.email="ci-bootstrap@users.noreply.github.com" \
    commit -m "ci: add four-phase CI workflow (via bootstrap-ci)"
git push -u origin ci-bootstrap/add-ci
gh pr create \
  --base "<default_branch>" --head "ci-bootstrap/add-ci" \
  --title "ci: add CI workflow (via bootstrap-ci)" \
  --body "Adds a four-phase CI workflow (build → test → sonar → push), generated from the **<build_system>** cookbook after classifying this repo as **<language>**. Sonar is skipped until a SONAR_TOKEN secret is set; the image push runs only on merges to <default_branch>. Review before merging."
```

Report back the **PR number and URL** (`gh pr create` prints the URL), plus a
one-line summary: what you classified the repo as, which cookbook you used, and
the reminder that Sonar/Push stay dormant until their secrets/registry are set
up.

## Extending: adding a new language / build system

This is the whole point of the cookbook design — it should be a one-file change:

1. Copy an existing cookbook (e.g. `references/cookbooks/pip.md`) to
   `references/cookbooks/<build_system>.md`.
2. Change only the language-specific parts: the toolchain setup step(s), the
   Build and Test commands, the Sonar scanner invocation, and the default
   Dockerfile. Keep the four named phases and both guards exactly as they are —
   see [references/skeleton.md](references/skeleton.md) for the contract every
   cookbook must satisfy.
3. Add a row for it to the two tables in step 3 above.

Nothing else changes. If you find yourself editing this SKILL.md's *workflow* to
support a new language, something has gone wrong — the per-language knowledge
belongs entirely in the cookbook.

## Reference files

- [references/skeleton.md](references/skeleton.md) — the fixed four-phase
  contract, the Sonar/Push guards, the placeholders, and the checklist for
  writing a new cookbook. Read this if a cookbook looks inconsistent or you're
  adding one.
- [references/cookbooks/](references/cookbooks/) — one file per supported build
  system, each a complete ci.yml template.
