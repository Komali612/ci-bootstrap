# Handoff — set this up on a new laptop (non-technical friendly)

Giving this project to a colleague who isn't technical? This gets them **all three
modes** working on their own laptop, using **their own test repositories** (the
assistant creates a couple for them):

- **CI only** — generate a CI pipeline and open a pull request.
- **CI + CD** — do CI, then **deploy the built app to their laptop** with Docker.
- **CD only** — deploy an app that CI already built.

…without hunting for any secret keys.

## What they actually need
- A **GitHub account** (they'll create their own test repos under it).
- **That's it to start.** GitHub sign-in is a browser click (`gh auth login`) — no
  key to copy by hand.
- **SonarCloud** (code-quality scan) and **Anthropic** (AI for unusual languages)
  keys are **optional** — skip them for a first working setup.
- For the **deploy** parts: **Docker Desktop** installed and running, plus a
  one-time runner attached to each repo they deploy (one command — see below).

## The two agents (this is the whole tool)
| Mode | Web page | What to pick |
|------|----------|--------------|
| CI only | http://127.0.0.1:8001/ | "① CI only — build the image" |
| CI + CD | http://127.0.0.1:8001/ | "② CI + CD — build & deploy" |
| CD only | http://127.0.0.1:8002/ | (deploys an already-built image) |

Both pages must be **running at the same time** to have all three modes available.
The prompt below starts both and keeps them up.

## How they use it
1. Install **Claude Code** and clone/open this project folder in it.
2. Make sure they have (or let the assistant install): Python 3.11+, git, the
   GitHub CLI (`gh`), and **Docker Desktop**.
3. Paste the prompt below into Claude Code and follow along.

## The prompt to paste

```
Hi Claude. I'm setting up this project (cicd-bootstrap) on my laptop and I'm NOT
technical — I don't write code and I've never done this before. Walk me through
everything from a fresh start: explain each step in plain English BEFORE you do
it, run all the terminal commands for me, and check each step actually worked
before moving on. Assume I know nothing.

I want ALL THREE modes working on this laptop, and I want to practice on MY OWN
test repositories (please CREATE them for me — I won't use anyone else's repos):
 - CI only  = generate a CI pipeline and open a pull request
 - CI + CD  = do CI, then deploy the built app to THIS laptop with Docker
 - CD only  = deploy an app that CI already built
so I can open the running app in my browser.

Please do all of this:

1. Check what's installed and install anything missing: Python 3.11+, git, the
   GitHub CLI (gh), and Docker Desktop. If Docker or any installer needs my Mac
   password, tell me and I'll type it — never ask me to paste a password in chat.
2. Sign me in to GitHub by running `gh auth login` with the browser option. This
   handles GitHub access so I don't have to create or copy any secret key by hand.
3. Run `bash setup.sh` to install the app.
4. About the two optional keys (SonarCloud and Anthropic): I don't have these and
   don't know how to get them. SKIP them for now — leave them blank in the .env
   file, and confirm everything still works without them. Offer to help me get
   them later if I ever want the code-quality scan.
5. Create TWO small .NET test repositories under MY OWN GitHub account for me to
   practice on. There's a helper script that builds a known-good .NET web service
   (with a working Dockerfile) and pushes it to a new repo for me — run it TWICE
   with DIFFERENT ports so I can run both at once:
       bash scripts/new-test-service.sh my-test-1 8080
       bash scripts/new-test-service.sh my-test-2 8081
   Give me the two repo URLs it prints. They have no CI/CD workflows on purpose —
   I'll generate those with the agents.
6. Start BOTH agents and keep them running the whole time, then give me both links:
     - CI agent (has "CI only" AND "CI + CD"):
         ./.venv/bin/python -m cicd_bootstrap.cli --serve --agent ci    -> http://127.0.0.1:8001/
     - CD agent (CD only):
         ./.venv/bin/python -m cicd_bootstrap.cli --serve --agent cd    -> http://127.0.0.1:8002/
   Explain which page and which button gives me each of the three modes.
7. For anything that DEPLOYS (CI + CD, or CD only): deploying to this laptop needs a
   "self-hosted runner" attached to that specific repo. There's a helper script for
   it — run `bash scripts/add-runner.sh <that repo's URL>` to download, register and
   start its runner (it uses the correct `laptop` label automatically), and make sure
   Docker Desktop is open, BEFORE we deploy. Remind me each new repo I deploy needs
   its own runner (run that script once per repo), or the deploy will just sit at
   "Waiting for a runner to pick up this job".
8. Walk me through my first full end-to-end run on ONE of the test repos you created:
   we do "CI + CD — build & deploy" on the 8001 page, wait for both pull requests to
   merge and the deploy to finish, then you confirm the app is actually running and
   give me the browser link to open it.
9. Also show me, in one line each, how I'd do "CI only" (8001) and "CD only" (8002)
   on my other test repo next time.

Important: never print my keys or passwords in the chat — anything sensitive goes
into the .env file only. If anything fails, explain what you see in plain English
and fix it before continuing.
```

## Things to tell them up front
- **The Mac password:** installing Docker Desktop may ask for their Mac login
  password. That's normal — *they* type it into the Mac's own popup, never in chat.
- **The assistant makes their test repos:** step 5 runs
  `bash scripts/new-test-service.sh <name> <port>` to create a couple of small .NET
  web services (with working Dockerfiles) under their own account — real repos to
  run all three modes against. Use different ports to run several at once.
- **Deploys need a runner per repo:** `bash scripts/add-runner.sh <repo-url>`
  downloads, registers, and starts it (run it once per repo). Without a runner, the
  deploy sits at "Waiting for a runner to pick up this job."
- **CD only comes after CI:** "CD only" (8002) deploys an image CI already built, so
  it only works on a repo that has already been through CI at least once.

## Their own keys, their own repos
Everything is per-person: they sign in as **themselves** and create **their own**
test repos, so PRs, runners, and deploys all happen under **their** GitHub account
and on **their** laptop. Nothing is shared with or routed through anyone else. The
`.env` file is git-ignored, so their keys never leave their machine.
