"""The CI agent — agent 1 of 2, with two modes:

* **CI only** — generate ``app-ci.yml``, open + auto-merge the CI PR so CI builds
  & pushes the image, then stop. Shows the CI PR.
* **CI + CD** — the whole chain, run as SHORT steps the page drives with polling
  (so it stays reliable even when the build takes minutes): open+merge CI (shows
  the CI PR) -> poll until the image is built -> open+merge CD (shows the CD PR).

Run it with:  cicd-bootstrap --serve --agent ci   (default port 8001)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from ..config import load_dotenv
from ..contracts import BootstrapResult, ChainResult
from ..core import add_cd_harness, bootstrap, run_ci_then_cd
from ..github import ci_run_status, resolve_token
from ..ingest import parse_repo_url
from .common import CD_AGENT_PORT, RENDER_JS, STYLE, add_shared_routes

app = FastAPI(title="cicd-bootstrap · CI agent", version="0.1.0")
add_shared_routes(app)


class CIRequest(BaseModel):
    repo_url: str
    open_pr: bool = True
    allow_llm_fallback: bool = False
    merge: bool = True


class CDRequest(BaseModel):
    repo_url: str
    open_pr: bool = True
    merge: bool = True
    auto_deploy: bool = True


class ChainRequest(BaseModel):
    repo_url: str
    allow_llm_fallback: bool = False
    auto_deploy: bool = True


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return INDEX_HTML


@app.post("/bootstrap", response_model=BootstrapResult)
def bootstrap_endpoint(req: CIRequest) -> BootstrapResult:
    return bootstrap(
        req.repo_url, open_pr_flag=req.open_pr,
        allow_llm_fallback=req.allow_llm_fallback, merge=req.merge,
    )


@app.post("/cd", response_model=BootstrapResult)
def cd_endpoint(req: CDRequest) -> BootstrapResult:
    # CI + CD deploys via Harness — the exact same path the CD agent uses, so both
    # agents behave identically for the CD half (no GitHub Actions deploy.yml / runner).
    return add_cd_harness(req.repo_url, open_pr_flag=req.open_pr, auto_deploy=req.auto_deploy)


@app.get("/ci-status")
def ci_status_endpoint(repo_url: str, sha: str) -> dict:
    # Single-shot status the page polls between the CI and CD steps.
    load_dotenv()
    owner, name = parse_repo_url(repo_url)
    return {"status": ci_run_status(owner, name, sha, resolve_token())}


@app.post("/chain", response_model=ChainResult)
def chain_endpoint(req: ChainRequest) -> ChainResult:
    # Blocking full chain — kept for API/CLI use; the web UI uses the polling flow.
    return run_ci_then_cd(req.repo_url, allow_llm_fallback=req.allow_llm_fallback, auto_deploy=req.auto_deploy)


_HEAD = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"/>'
    '<meta name="viewport" content="width=device-width, initial-scale=1"/>'
    '<title>CI agent · cicd-bootstrap</title>' + STYLE + '</head><body>'
)

_BODY = f'''<span class="step">Agent 1 of 2 · CI</span>
<h1>⚙️ CI agent</h1>
<p class="sub">Give a service repo, then pick how far to take it. <strong>CI only</strong> builds &amp; pushes the image and stops — deploy later from the <a href="http://localhost:{CD_AGENT_PORT}/">CD agent</a>. <strong>CI + CD</strong> does the whole thing (build the image, then deploy it to your laptop <strong>via Harness</strong> — the same as the CD agent) and shows you the CI pull request live. &nbsp;·&nbsp; <a href="/dashboard">📊 dashboard</a></p>
<div class="opts">
  <label class="chk"><input type="radio" name="mode" value="ci" checked/> ① CI only — build the image</label>
  <label class="chk"><input type="radio" name="mode" value="full"/> ② CI + CD — build &amp; deploy</label>
</div>
<form id="f">
  <input id="url" type="url" required placeholder="https://github.com/owner/repo" autocomplete="off"/>
  <button id="go" type="submit">Run CI agent</button>
</form>
<div class="opts">
  <label class="chk"><input id="pr" type="checkbox" checked/> open a pull request</label>
  <label class="chk"><input id="llm" type="checkbox"/> LLM fallback for unsupported languages</label>
  <label class="chk full-only" style="display:none" title="Checked: the deploy runs with no approval step (fully hands-off). Unchecked: production waits for a click-to-approve."><input id="auto" type="checkbox" checked/> deploy without approval (hands-off)</label>
</div>
<div id="out"></div>'''

_SCRIPT = '''<script>
const f=document.getElementById('f'),out=document.getElementById('out'),go=document.getElementById('go');
function mode(){ return document.querySelector('input[name=mode]:checked').value; }
function syncMode(){ const m=mode(); document.querySelectorAll('.full-only').forEach(e=>e.style.display=(m==='full')?'':'none'); }
document.querySelectorAll('input[name=mode]').forEach(r=>r.addEventListener('change',syncMode)); syncMode();
function banner(id,cls,txt){ const el=document.getElementById(id); if(el) el.innerHTML='<div class="banner '+cls+'">'+txt+'</div>'; }
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function runCiOnly(repo_url, allow_llm_fallback){
  const open_pr=document.getElementById('pr').checked;
  out.innerHTML='<div class="card"><span class="spin"></span>CI: generate, open PR, merge, build the image\\u2026</div>';
  const data=await (await fetch('/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url,open_pr,allow_llm_fallback,merge:true})})).json();
  render(data);
  if(data.merged){ out.insertAdjacentHTML('beforeend','<div class="banner warn" style="margin-top:8px">\\ud83d\\udce6 CI is now building the image on GitHub cloud runners \\u2014 watch the Actions tab. Then run the CD agent to deploy.</div>'); }
}

async function runFull(repo_url, allow_llm_fallback, auto_deploy){
  out.innerHTML=''
    +'<h3 class="sec">\\u2699\\ufe0f CI pull request</h3><div id="ci"><div class="card"><span class="spin"></span>opening &amp; merging the CI PR\\u2026</div></div>'
    +'<div id="imgstatus"></div>'
    +'<h3 class="sec">\\ud83d\\ude80 CD pull request</h3><div id="cd"><div class="banner warn">waiting for the image\\u2026</div></div>'
    +'<div id="donemsg"></div>';
  let ci;
  try{ ci=await (await fetch('/bootstrap',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url,open_pr:true,allow_llm_fallback,merge:true})})).json(); }
  catch(e){ banner('ci','err','CI request failed: '+esc(String(e))); return; }
  renderOne(ci,'ci');
  if(ci.status!=='opened'||!ci.merged){ banner('imgstatus','err','CI stopped: '+esc(ci.message)); return; }
  let ready=false;
  for(let i=0;i<90;i++){
    banner('imgstatus','warn','\\u23f3 building the image on GitHub cloud\\u2026 ('+(i*12)+'s)');
    await sleep(12000);
    let s; try{ s=await (await fetch('/ci-status?repo_url='+encodeURIComponent(repo_url)+'&sha='+encodeURIComponent(ci.merge_sha||''))).json(); }catch(e){ continue; }
    if(s.status==='success'){ ready=true; break; }
    if(s.status==='failure'){ banner('imgstatus','err','\\u274c CI failed on main \\u2014 check the Actions tab.'); return; }
  }
  if(!ready){ banner('imgstatus','warn','\\u23f3 image still building (timed out here). It will finish; re-run CD or use the CD agent once it is done.'); return; }
  banner('imgstatus','ok','\\ud83d\\udce6 Image built &amp; pushed to GHCR');
  document.getElementById('cd').innerHTML='<div class="card"><span class="spin"></span>opening &amp; merging the CD PR\\u2026</div>';
  let cd;
  try{ cd=await (await fetch('/cd',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({repo_url,open_pr:true,merge:true,auto_deploy})})).json(); }
  catch(e){ banner('cd','err','CD request failed: '+esc(String(e))); return; }
  renderOne(cd,'cd');
  const okdone=(cd.status==='opened'&&cd.merged);
  banner('donemsg', okdone?'ok':'warn', okdone?'\\u2705 Both pipelines merged. The deploy runs automatically on the next build.':('CD: '+esc(cd.message)));
}

f.addEventListener('submit',async e=>{
  e.preventDefault();
  const repo_url=document.getElementById('url').value.trim();
  const allow_llm_fallback=document.getElementById('llm').checked;
  go.disabled=true;
  try{
    if(mode()==='full'){ await runFull(repo_url, allow_llm_fallback, document.getElementById('auto').checked); }
    else{ await runCiOnly(repo_url, allow_llm_fallback); }
  }catch(err){ out.innerHTML='<div class="banner err">Request failed: '+esc(String(err))+'</div>'; }
  finally{ go.disabled=false; }
});
''' + RENDER_JS + '''
</script>'''

INDEX_HTML = _HEAD + _BODY + _SCRIPT + '</body></html>'
