"""Tests for the LangGraph CI -> CD orchestration (graph.py).

Nodes are stubbed by monkeypatching the functions on the ``core`` module (the
graph resolves them there at call time), so no network / LLM is touched.
"""

from __future__ import annotations

from cicd_bootstrap import core, graph
from cicd_bootstrap.contracts import BootstrapResult


def _ci(status="opened", merged=True, sha="abc123"):
    return BootstrapResult(
        repo_url="https://github.com/a/b", status=status, kind="ci", pr_number=1,
        merged=merged, merge_sha=(sha if merged else None), message="opened PR #1",
    )


def _cd(status="opened"):
    return BootstrapResult(
        repo_url="https://github.com/a/b", status=status, kind="cd", pr_number=2, message="opened PR #2",
    )


def _init():
    return {"repo_url": "https://github.com/a/b", "owner": "a", "name": "b", "image_ready": False}


def _stub(monkeypatch, *, ci=None, ready=True, cd=None, reached=None):
    monkeypatch.setattr(core, "bootstrap", lambda url, **kw: ci if ci is not None else _ci())
    monkeypatch.setattr(core, "wait_for_ci_success", lambda *a, **k: ready)

    def _cd_fn(url, **kw):
        if reached is not None:
            reached["cd"] = True
        return cd if cd is not None else _cd()

    monkeypatch.setattr(core, "add_cd_harness", _cd_fn)


def test_graph_happy_path(monkeypatch):
    _stub(monkeypatch)
    final = graph.build_cicd_graph().invoke(_init(), config={"configurable": {"thread_id": "t1"}})
    assert final["image_ready"] is True
    assert final["cd"].status == "opened"
    assert "done" in final["message"].lower()


def test_graph_stops_when_ci_not_merged(monkeypatch):
    reached = {"cd": False}
    _stub(monkeypatch, ci=_ci(merged=False), reached=reached)
    final = graph.build_cicd_graph().invoke(_init(), config={"configurable": {"thread_id": "t2"}})
    assert final.get("image_ready") is False
    assert final.get("cd") is None
    assert reached["cd"] is False  # CD node never ran


def test_graph_stops_when_image_never_ready(monkeypatch):
    reached = {"cd": False}
    _stub(monkeypatch, ready=False, reached=reached)
    final = graph.build_cicd_graph().invoke(_init(), config={"configurable": {"thread_id": "t3"}})
    assert final.get("image_ready") is False and final.get("cd") is None and reached["cd"] is False
    assert "image" in final["message"].lower()


def test_graph_human_in_the_loop_pauses_then_resumes(monkeypatch):
    """interrupt_before_deploy pauses right before CD; resuming runs the deploy."""
    _stub(monkeypatch)
    app = graph.build_cicd_graph(interrupt_before_deploy=True)
    cfg = {"configurable": {"thread_id": "approval-1"}}

    paused = app.invoke(_init(), config=cfg)
    assert paused.get("image_ready") is True  # CI done, image built
    assert paused.get("cd") is None           # ...but paused before deploying

    resumed = app.invoke(None, config=cfg)     # human approved -> resume
    assert resumed["cd"].status == "opened"
