"""Shared UI pieces for the two agents: page styling, the result-rendering JS,
and the routes both agents expose (health + the shared telemetry dashboard).

Keeping these here means the CI agent and the CD agent look and behave
consistently without duplicating the big style/render blocks."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from .. import telemetry
from ..service import DASHBOARD_HTML

# The CD agent listens here by default; used to cross-link the two agents.
CI_AGENT_PORT = 8001
CD_AGENT_PORT = 8002

STYLE = """<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         max-width: 820px; margin: 40px auto; padding: 0 20px; line-height: 1.5; }
  h1 { font-size: 1.5rem; margin-bottom: .25rem; }
  p.sub { color: #6b7280; margin-top: 0; }
  form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 24px 0 8px; }
  input[type=url] { flex: 1 1 340px; padding: 10px 12px; font-size: 1rem;
                    border: 1px solid #9ca3af; border-radius: 8px; }
  button { padding: 10px 18px; font-size: 1rem; font-weight: 600; border: 0; border-radius: 8px;
           background: #2a78d6; color: #fff; cursor: pointer; }
  button:disabled { opacity: .6; cursor: progress; }
  label.chk { font-size: .9rem; color: #6b7280; display: flex; align-items: center; gap: 6px; }
  .opts { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; margin: 4px 0 8px; }
  .step { display:inline-block; font-size:.75rem; font-weight:600; padding:2px 10px; border-radius:999px;
          background: rgba(42,120,214,.14); color:#2a78d6; margin-bottom:6px; }
  .card { border: 1px solid #d1d5db; border-radius: 10px; padding: 16px; margin-top: 12px; }
  .banner { padding: 12px 16px; border-radius: 10px; font-weight: 600; }
  .ok { background: rgba(12,163,12,.12); color: #0ca30c; }
  .warn { background: rgba(42,120,214,.12); color: #2a78d6; }
  .err { background: rgba(208,59,59,.12); color: #d03b3b; }
  a { color: #2a78d6; }
  code { background: rgba(127,127,127,.14); padding: 1px 5px; border-radius: 5px; }
  table { border-collapse: collapse; width: 100%; font-size: .92rem; }
  td { padding: 4px 8px; border-bottom: 1px solid #e5e7eb; vertical-align: top; }
  td.k { color: #6b7280; width: 140px; }
  .phases { display: flex; gap: 6px; flex-wrap: wrap; margin: 6px 0 0; }
  .phase { font-size: .8rem; padding: 2px 8px; border-radius: 999px; background: rgba(42,120,214,.14); color: #2a78d6; }
  pre { background: rgba(127,127,127,.12); padding: 12px; border-radius: 8px; overflow-x: auto; font-size: .82rem; }
  .spin { display: inline-block; width: 14px; height: 14px; border: 2px solid currentColor;
          border-right-color: transparent; border-radius: 50%; animation: r .7s linear infinite;
          vertical-align: -2px; margin-right: 8px; }
  @keyframes r { to { transform: rotate(360deg); } }
</style>"""

# Renders a BootstrapResult (CI or CD) into the #out div. Shared by both agents:
# CI results carry a classification; CD results carry cd_gate; both carry a workflow.
RENDER_JS = """
function esc(s){ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function row(k, v){ return '<tr><td class="k">' + k + '</td><td>' + (v==null?'':v) + '</td></tr>'; }
function renderOne(r, targetId){
  const out = document.getElementById(targetId || 'out');
  let h = '';
  if (r.status === 'opened') {
    h += '<div class="banner ok">\\u2705 Opened PR #' + r.pr_number + ' \\u2014 <a href="' + esc(r.pr_url) + '" target="_blank" rel="noopener">' + esc(r.pr_url) + '</a></div>';
  } else if (r.status === 'generated') {
    h += '<div class="banner warn">\\u2139\\ufe0f Workflow generated (no PR opened)</div>';
  } else if (r.status === 'blocked') {
    h += '<div class="banner warn">\\u23f3 ' + esc(r.message) + '</div>';
  } else {
    h += '<div class="banner err">\\u274c ' + esc(r.message) + '</div>';
  }
  if (r.merged) {
    h += '<div class="banner ok">\\ud83d\\udd00 Auto-merged to the main branch</div>';
  }
  if (r.sonar_project === 'created' || r.sonar_project === 'exists') {
    h += '<div class="banner ok">\\ud83e\\udd9a SonarCloud project ' + (r.sonar_project === 'created' ? 'created (Automatic Analysis off)' : 'already set up') + '</div>';
  } else if (r.sonar_project === 'error') {
    h += '<div class="banner warn">\\u26a0\\ufe0f Could not provision the SonarCloud project \\u2014 the first scan may need manual setup</div>';
  }
  if (r.sonar_secret_set === true) {
    h += '<div class="banner ok">\\ud83d\\udd10 SONAR_TOKEN written to the repo\\u2019s Actions secrets</div>';
  } else if (r.sonar_secret_set === false) {
    h += '<div class="banner warn">\\u26a0\\ufe0f Could not set SONAR_TOKEN (token needs admin/secrets:write) \\u2014 Sonar will stay skipped</div>';
  }
  if (r.cd_gate) {
    h += '<div class="banner warn">\\ud83d\\udea6 Approval to production: ' + esc(r.cd_gate) + '</div>';
  }
  const c = r.classification;
  if (c) {
    h += '<div class="card"><strong>Classification</strong><table>'
      + row('language', esc(c.language)) + row('build system', esc(c.build_system))
      + row('test command', esc(c.test_command))
      + row('confidence', esc(c.confidence + ' (via ' + c.method + ')'))
      + row('evidence', (c.evidence||[]).map(esc).join('<br>'))
      + '</table></div>';
  }
  const w = r.workflow;
  if (w) {
    const src = w.llm_authored
      ? ' <span class="sub">(cookbook: ' + esc(w.cookbook) + ' \\u2014 \\ud83e\\udd16 LLM-authored)</span>'
      : ' <span class="sub">(cookbook: ' + esc(w.cookbook) + ')</span>';
    h += '<div class="card"><strong>Generated workflow</strong> \\u2014 <code>' + esc(w.path) + '</code>' + src
      + '<div class="phases">' + (w.phases||[]).map(p => '<span class="phase">' + esc(p) + '</span>').join('') + '</div>'
      + (w.llm_authored ? '<div class="banner warn" style="margin-top:10px">\\u26a0\\ufe0f No built-in cookbook for this stack \\u2014 the setup/build/test/Dockerfile were generated by the LLM. Review the commands before merging.</div>' : '')
      + '<pre>' + esc(w.content) + '</pre></div>';
  }
  out.innerHTML = h;
}
function render(r){ renderOne(r, 'out'); }
"""


def add_shared_routes(app: FastAPI) -> None:
    """Give an agent app the health probe and the shared telemetry dashboard."""

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard() -> str:
        return DASHBOARD_HTML

    @app.get("/telemetry/data")
    def telemetry_data() -> dict:
        return telemetry.summary()
