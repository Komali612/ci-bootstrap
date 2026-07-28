# Setup guide — run ci-bootstrap on your laptop

This guide takes you from a fresh clone to a working tool. **No coding experience needed** —
follow it top to bottom. Two ways to do it:

- **Easiest — let an AI assistant walk you through it.** Open this folder in Claude Code and
  paste: *"Follow SETUP.md and set me up from scratch. I'm not technical — explain each step,
  run the commands for me, help me get every key, and check each step worked before moving on."*
- **Or do it yourself** with the steps below.

Either way, you'll need three free/low-cost things: a **GitHub** account, an **Anthropic** API
key, and a **SonarCloud** account. This guide gets you all of them.

---

## What this tool does (30 seconds)

You give it a GitHub repository. It looks at the code, figures out how it's built, writes a
complete CI pipeline (build → test → security scan → publish), and opens a pull request adding
it. You review and merge. That's it.

---

## Step 1 — Install the basic tools

You need three programs. Check if you already have them, and install any that are missing.

| Tool | Check (in a terminal) | If missing |
|------|----------------------|------------|
| **Python 3.11+** | `python3 --version` | Download from <https://www.python.org/downloads/> |
| **git** | `git --version` | Download from <https://git-scm.com/downloads> |
| **GitHub CLI** | `gh --version` | Download from <https://cli.github.com> |

> **Windows:** the setup script below expects a Unix-style shell. Use **Git Bash** (installed
> with git) or **WSL**, or just use the AI-assistant option above — it will adapt to Windows.

---

## Step 2 — Get your accounts and keys

You'll paste these into a file in Step 3. **Never paste a secret key into a chat window** — they
go into the file only.

### 2a. GitHub (free)
1. If you don't have an account, create one at <https://github.com>.
2. In your terminal, run `gh auth login` and follow the browser prompts (choose GitHub.com →
   HTTPS → log in with a browser). This lets the tool open pull requests and set up secrets in
   your repositories.

### 2b. Anthropic API key — the AI part *(small paid step, ~$5)*
1. Go to <https://console.anthropic.com> and sign up.
2. Open **Billing** and add a small amount of credit — **$5 is plenty** for lots of runs.
3. Open **API Keys → Create Key**. Copy the key — it looks like `sk-ant-...`.

### 2c. SonarCloud — the security & quality scan *(free for public repos)*
1. Go to <https://sonarcloud.io> and **sign in with GitHub**.
2. Create an **organization** (choose the free plan for public repositories). Note its
   **key** (shown in the URL / org settings) — you'll use it as `SONAR_ORG`.
3. Go to **My Account → Security → Generate Token**, name it, and copy the token.

---

## Step 3 — Set up the project

From the project folder, run:

```
bash setup.sh
```

This checks your tools, creates an isolated Python environment, installs the app, creates your
`.env` file, and tells you which keys are still missing.

Then open the newly created **`.env`** file in any text editor and paste your three values
(no quotes, no spaces):

```
ANTHROPIC_API_KEY=sk-ant-...your key...
SONAR_TOKEN=...your sonarcloud token...
SONAR_ORG=your-sonarcloud-org-key
```

Save it, then run `bash setup.sh` again — all three keys should now show a green ✓.

---

## Step 4 — Start it and try it

Start the service:

```
./.venv/bin/python -m ci_bootstrap.cli --serve
```

When you see `Uvicorn running on http://127.0.0.1:8000`, open **<http://127.0.0.1:8000/>** in
your browser. Leave that terminal window open (it *is* the running app; press **Ctrl+C** to stop).

Now try it on one of your own repositories:
1. Pick a GitHub repo **you own** (ideally **public**, so SonarCloud is free).
2. Paste its URL into the page and click **Run**.
3. It classifies the repo, generates the pipeline, and opens a **pull request** — click through
   to review it on GitHub.

That's a full working setup. 🎉

---

## Troubleshooting

- **`bash setup.sh` says Python is missing** — install Python 3.11+ (link in Step 1), close and
  reopen your terminal, and run it again.
- **A key shows ✗ MISSING** — open `.env`, make sure the value is on the same line as the `=`
  with no spaces or `#` comment after it, save, and re-run `bash setup.sh`.
- **"no GitHub token available"** when opening a PR — run `gh auth login` and try again.
- **The Sonar scan is skipped or fails** — for a brand-new SonarCloud project, create the project
  once under your org and **turn off "Automatic Analysis"** (Administration → Analysis Method) so
  the pipeline's own scan is used.
- **Port already in use** — something's already running on 8000. Stop it, or start on another
  port: `./.venv/bin/python -m ci_bootstrap.cli --serve --port 8010`.

Stuck on any step? Open this folder in Claude Code and describe exactly what you see — it can pick
up from wherever you are.
