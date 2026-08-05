"""Tests for auto-merge and the full CI->CD chain orchestration (all mocked)."""

from __future__ import annotations

from types import SimpleNamespace

from cicd_bootstrap import core
from cicd_bootstrap.contracts import BootstrapResult


# --- _maybe_merge --------------------------------------------------------

def test_maybe_merge_disabled_is_noop():
    merged, sha, msg = core._maybe_merge(SimpleNamespace(owner="a", name="b"), 5, "tok", merge=False)
    assert merged is False and sha is None and msg == ""


def test_maybe_merge_success(monkeypatch):
    monkeypatch.setattr(core, "merge_pr", lambda o, n, pr, tok: "sha999")
    merged, sha, msg = core._maybe_merge(SimpleNamespace(owner="a", name="b"), 5, "tok", merge=True)
    assert merged is True and sha == "sha999" and "merged" in msg


def test_maybe_merge_failure_is_non_fatal(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("protected branch")
    monkeypatch.setattr(core, "merge_pr", boom)
    merged, sha, msg = core._maybe_merge(SimpleNamespace(owner="a", name="b"), 5, "tok", merge=True)
    assert merged is False and sha is None and "auto-merge failed" in msg


# --- run_ci_then_cd ------------------------------------------------------

def _ci(status="opened", merged=True, sha="abc123"):
    return BootstrapResult(
        repo_url="https://github.com/a/b", status=status, kind="ci", pr_number=1,
        merged=merged, merge_sha=(sha if merged else None), message="opened PR #1",
    )


def _cd(status="opened", merged=True):
    return BootstrapResult(
        repo_url="https://github.com/a/b", status=status, kind="cd", pr_number=2,
        merged=merged, message="opened PR #2",
    )


def _base(monkeypatch):
    monkeypatch.setattr(core, "resolve_token", lambda: "tok")
    monkeypatch.setattr(core, "parse_repo_url", lambda url: ("a", "b"))


def test_chain_happy_path(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(core, "bootstrap", lambda url, **kw: _ci())
    monkeypatch.setattr(core, "wait_for_ci_success", lambda o, n, sha, tok, **kw: True)
    monkeypatch.setattr(core, "add_cd_harness", lambda url, **kw: _cd())
    res = core.run_ci_then_cd("https://github.com/a/b", token="tok")
    assert res.image_ready is True
    # CD is now Harness: success = the CD result opened (pipeline provisioned), not merged.
    assert res.ci.merged and res.cd is not None and res.cd.status == "opened"
    assert "done" in res.message.lower()


def test_chain_stops_if_ci_merge_fails(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(core, "bootstrap", lambda url, **kw: _ci(merged=False))
    reached = {"cd": False}
    monkeypatch.setattr(core, "wait_for_ci_success", lambda *a, **k: True)
    monkeypatch.setattr(core, "add_cd_harness", lambda url, **kw: reached.__setitem__("cd", True) or _cd())
    res = core.run_ci_then_cd("https://github.com/a/b", token="tok")
    assert res.image_ready is False and res.cd is None and reached["cd"] is False


def test_chain_stops_if_image_never_ready(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(core, "bootstrap", lambda url, **kw: _ci())
    monkeypatch.setattr(core, "wait_for_ci_success", lambda *a, **k: False)  # timed out
    reached = {"cd": False}
    monkeypatch.setattr(core, "add_cd_harness", lambda url, **kw: reached.__setitem__("cd", True) or _cd())
    res = core.run_ci_then_cd("https://github.com/a/b", token="tok")
    assert res.image_ready is False and res.cd is None and reached["cd"] is False
    assert "image" in res.message.lower()
