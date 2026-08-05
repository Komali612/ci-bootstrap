"""Tests for the CD (deploy) workflow generator, incl. the handoff toggle."""

from __future__ import annotations

import yaml

from cicd_bootstrap.contracts import RepoSnapshot
from cicd_bootstrap.deploy import CD_WORKFLOW_PATH, detect_port, generate_cd, render_cd_workflow


def _snap(manifests=None):
    return RepoSnapshot(
        repo_url="https://github.com/acme/widget",
        owner="Acme", name="Widget", default_branch="main",
        tree=["app/main.py"], manifests=manifests or {},
    )


def _on(wf):
    # PyYAML may read the (quoted) key "on" as the string "on"; be robust either way.
    return wf.get("on", wf.get(True))


def test_path_image_and_cookbook():
    gw = generate_cd(_snap())
    assert gw.path == ".github/workflows/deploy.yml" == CD_WORKFLOW_PATH
    assert "ghcr.io/acme/widget" in gw.content       # image ref lowercased
    assert gw.cookbook == "local-docker"


def test_auto_handoff_includes_workflow_run():
    wf = yaml.safe_load(render_cd_workflow(_snap(), auto_handoff=True))
    on = _on(wf)
    assert "workflow_run" in on and "workflow_dispatch" in on
    assert on["workflow_run"]["workflows"] == ["CI"]


def test_manual_handoff_is_dispatch_only():
    wf = yaml.safe_load(render_cd_workflow(_snap(), auto_handoff=False))
    on = _on(wf)
    assert "workflow_run" not in on
    assert "workflow_dispatch" in on


def test_manual_approval_gate_default_and_auto_deploy_drops_it():
    default = yaml.safe_load(render_cd_workflow(_snap()))
    assert default["jobs"]["deploy"]["environment"] == "production"
    auto = yaml.safe_load(render_cd_workflow(_snap(), auto_deploy=True))
    assert "environment" not in auto["jobs"]["deploy"]


def test_detect_port_from_dockerfile():
    snap = _snap(manifests={"Dockerfile": "FROM python:3.12-slim\nEXPOSE 9000\n"})
    assert detect_port(snap) == 9000
    assert 'PORT="9000"' in render_cd_workflow(snap)  # deploy step binds the detected port


def test_cd_pr_blocked_until_ci_pushes_an_image(tmp_path, monkeypatch):
    """Opening the CD PR is gated on CI having produced an image."""
    from cicd_bootstrap import core
    monkeypatch.setenv("CI_BOOTSTRAP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "load_dotenv", lambda: None)
    monkeypatch.setattr(core, "ingest", lambda url, workdir, token=None: _snap())
    monkeypatch.setattr(core, "_image_available", lambda snap, token: False)  # no image yet

    r = core.add_cd("https://github.com/acme/widget", open_pr_flag=True, token="tok")
    assert r.status == "blocked" and r.kind == "cd"
    assert "image" in r.message.lower()
    assert r.pr_number is None  # nothing was opened


def test_cd_dry_run_previews_even_without_image(tmp_path, monkeypatch):
    """A no-PR preview still generates the deploy.yml even before CI has run."""
    from cicd_bootstrap import core
    monkeypatch.setenv("CI_BOOTSTRAP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(core, "load_dotenv", lambda: None)
    monkeypatch.setattr(core, "ingest", lambda url, workdir, token=None: _snap())
    monkeypatch.setattr(core, "_image_available", lambda snap, token: False)

    r = core.add_cd("https://github.com/acme/widget", open_pr_flag=False, token="tok")
    assert r.status == "generated"
    assert r.workflow.path.endswith("deploy.yml")
