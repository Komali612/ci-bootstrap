"""The CD agent — agent 2 of 2.

Picks up after the CI agent: given a repo whose CI pipeline is building an image
in GHCR, it generates the CD pipeline (``deploy.yml``) that pulls that image and
deploys it to the self-hosted runner (recreate, health-check, rollback), and
opens a pull request. Approval to production is on by default (click-to-approve).

Run it with:  cicd-bootstrap --serve --agent cd   (default port 8002)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..contracts import BootstrapResult
from ..core import add_cd, add_cd_harness
from .common import CI_AGENT_PORT, RENDER_JS, STYLE, add_shared_routes

app = FastAPI(title="cicd-bootstrap · CD agent", version="0.1.0")
add_shared_routes(app)


class CDRequest(BaseModel):
    repo_url: str
    target: str = "harness"  # "harness" (default) or "github" (Actions deploy.yml)
    open_pr: bool = True
    auto_deploy: bool = False
    auto_handoff: bool = True
    merge: bool = True  # auto-merge the CD PR after opening it


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return INDEX_HTML


@app.post("/cd", response_model=BootstrapResult)
def cd_endpoint(req: CDRequest) -> BootstrapResult:
    if req.target == "harness":
        # Harness: Git-stored pipeline + webhook trigger + notify-workflow PR.
        # (auto_handoff/merge are GitHub-Actions concepts and don't apply here.)
        return add_cd_harness(req.repo_url, auto_deploy=req.auto_deploy, open_pr_flag=req.open_pr)
    return add_cd(
        req.repo_url, open_pr_flag=req.open_pr,
        auto_deploy=req.auto_deploy, auto_handoff=req.auto_handoff, merge=req.merge,
    )


_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
    '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
    '<title>CD agent · cicd-bootstrap</title>' + STYLE + '</head><body>'
)

_BODY = f'''<span class="step">Agent 2 of 2 · CD</span>
<h1>🚀 CD agent</h1>
<p class="sub">Run this <strong>after</strong> the <a href="http://localhost:{CI_AGENT_PORT}/">CI agent</a> has built an image. Give it the same repo, then pick a <strong>deploy target</strong>. &nbsp;·&nbsp; <a href="/dashboard">📊 dashboard</a></p>
<div class="opts">
  <label class="chk"><input type="radio" name="target" value="harness" checked/> 🟣 Harness — Git-stored pipeline, deploy via the Harness delegate <strong>(default)</strong></label>
  <label class="chk"><input type="radio" name="target" value="github"/> ⚙️ GitHub Actions — <code>deploy.yml</code> on a self-hosted runner</label>
</div>
<form id="f">
  <input id="url" type="url" required placeholder="https://github.com/owner/repo" autocomplete="off"/>
  <button id="go" type="submit">Run CD agent</button>
</form>
<div class="opts">
  <label class="chk"><input id="pr" type="checkbox" checked/> open a pull request</label>
  <label class="chk gh-only" title="Checked: the CD PR is merged to main automatically after it's opened. Unchecked: it's left open for you to merge."><input id="merge" type="checkbox" checked/> auto-merge the CD PR</label>
  <label class="chk gh-only" title="Checked: the deploy runs automatically right after CI finishes (auto-handoff). Unchecked: the deploy runs only when you trigger it yourself from GitHub's Actions tab (manual)."><input id="handoff" type="checkbox" checked/> auto-handoff (deploy right after CI)</label>
  <label class="chk" title="Checked: deploy straight to production. Unchecked: pause for a click-to-approve (a GitHub environment, or a Harness approval stage)."><input id="auto" type="checkbox"/> deploy automatically (else: click to approve)</label>
</div>
<div id="out"></div>'''

_SCRIPT = '''<script>
const f=document.getElementById('f'),out=document.getElementById('out'),go=document.getElementById('go');
function target(){ return document.querySelector('input[name=target]:checked').value; }
function syncTarget(){ const h=target()==='harness';
  document.querySelectorAll('.gh-only').forEach(e=>e.style.display=h?'none':''); }
document.querySelectorAll('input[name=target]').forEach(r=>r.addEventListener('change',syncTarget)); syncTarget();
f.addEventListener('submit',async e=>{
  e.preventDefault();
  const repo_url=document.getElementById('url').value.trim();
  const tgt=target();
  const open_pr=document.getElementById('pr').checked;
  const auto_deploy=document.getElementById('auto').checked;
  const auto_handoff=document.getElementById('handoff').checked;
  const merge=document.getElementById('merge').checked;
  go.disabled=true;
  const via=(tgt==='harness')?'Provisioning Harness (pipeline, connector, webhook)':'Cloning, generating deploy workflow';
  out.innerHTML='<div class="card"><span class="spin"></span>'+via+(open_pr?', opening PR':'')+'\\u2026</div>';
  try{
    const resp=await fetch('/cd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url,target:tgt,open_pr,auto_deploy,auto_handoff,merge})});
    render(await resp.json());
  }catch(err){ out.innerHTML='<div class="banner err">Request failed: '+esc(String(err))+'</div>'; }
  finally{ go.disabled=false; }
});
''' + RENDER_JS + '''
</script>'''

INDEX_HTML = _HEAD + _BODY + _SCRIPT + '</body></html>'
