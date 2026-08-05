"""Offline tests for telemetry recording, aggregation, and the endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from cicd_bootstrap import telemetry
from cicd_bootstrap.contracts import BootstrapResult, Classification, GeneratedWorkflow
from cicd_bootstrap.service import app


def _result(status="opened", method="llm", build="maven", llm_authored=False, pr=7, sonar=True):
    return BootstrapResult(
        repo_url="https://github.com/acme/widget.git",
        status=status,
        classification=Classification(
            language="java", build_system=build, test_command="mvn -B verify",
            confidence=0.99, method=method, llm_input_tokens=1200, llm_output_tokens=140,
        ),
        workflow=GeneratedWorkflow(
            path=".github/workflows/ci.yml", content="name: CI", cookbook=build,
            llm_authored=llm_authored,
            llm_input_tokens=(900 if llm_authored else None),
            llm_output_tokens=(300 if llm_authored else None),
        ),
        pr_number=pr, sonar_secret_set=sonar, message="ok",
    )


def test_record_then_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_BOOTSTRAP_DATA_DIR", str(tmp_path))
    telemetry.record(_result(), 2500)
    events = telemetry.load_events()
    assert len(events) == 1
    e = events[0]
    assert e["repo"] == "acme/widget"          # parsed + .git stripped
    assert e["status"] == "opened" and e["build_system"] == "maven"
    assert e["duration_ms"] == 2500 and e["pr_number"] == 7
    assert e["classify_method"] == "llm" and e["sonar_secret_set"] is True


def test_event_records_error_message_only_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_BOOTSTRAP_DATA_DIR", str(tmp_path))
    ok = telemetry._event(_result(status="opened"), 100)
    err = telemetry._event(BootstrapResult(repo_url="https://github.com/a/b", status="error", message="boom"), 100)
    assert ok["error"] is None
    assert err["error"] == "boom"


def test_aggregate_computes_totals_and_rates():
    events = [
        telemetry._event(_result(status="opened", method="llm", build="maven"), 1000),
        telemetry._event(_result(status="opened", method="heuristic", build="dotnet"), 3000),
        telemetry._event(_result(status="opened", method="llm", build="go", llm_authored=True), 5000),
        telemetry._event(BootstrapResult(repo_url="https://github.com/a/b", status="error", message="x"), 200),
    ]
    agg = telemetry.aggregate(events)
    assert agg["totals"]["runs"] == 4
    assert agg["totals"]["opened"] == 3 and agg["totals"]["errors"] == 1
    assert agg["rates"]["success_rate"] == 75.0          # 3 of 4
    assert agg["rates"]["llm_classify_rate"] == 66.7     # 2 of 3 classified
    assert agg["rates"]["fallback_rate"] == 33.3         # 1 of 3 workflows llm-authored
    assert agg["tokens"]["total"] > 0 and agg["cost_estimate_usd"] > 0
    assert agg["latency_ms"]["p50"] >= 1000
    langs = {d["key"]: d["count"] for d in agg["by_build_system"]}
    assert langs == {"maven": 1, "dotnet": 1, "go": 1}
    assert len(agg["runs_per_day"]) == 14


def test_aggregate_empty_is_safe():
    agg = telemetry.aggregate([])
    assert agg["totals"]["runs"] == 0
    assert agg["rates"]["success_rate"] == 0.0
    assert agg["latency_ms"]["p95"] == 0


def _cd_result(status="opened", gate="manual approval (production environment)", pr=8):
    return BootstrapResult(
        repo_url="https://github.com/acme/widget.git",
        status=status, kind="cd", cd_gate=gate,
        workflow=GeneratedWorkflow(
            path=".github/workflows/cd.yml", content="name: CD", cookbook="local-docker",
            phases=["pull", "deploy", "health-check", "rollback"],
        ),
        pr_number=pr, message="ok",
    )


def test_cd_telemetry_is_tracked_separately():
    events = [
        telemetry._event(_result(status="opened", build="maven"), 1000),                 # CI
        telemetry._event(_result(status="opened", build="go", llm_authored=True), 1200),  # CI (fallback)
        telemetry._event(_cd_result(gate="manual approval"), 500),                        # CD manual
        telemetry._event(_cd_result(gate="automatic (no gate)"), 400),                    # CD auto
    ]
    agg = telemetry.aggregate(events)
    assert agg["totals"]["runs"] == 4
    assert agg["totals"]["ci_runs"] == 2 and agg["totals"]["cd_runs"] == 2
    assert agg["cd"]["runs"] == 2 and agg["cd"]["prs_opened"] == 2
    assert agg["cd"]["success_rate"] == 100.0
    assert {d["key"]: d["count"] for d in agg["by_kind"]} == {"ci": 2, "cd": 2}
    assert {d["key"]: d["count"] for d in agg["by_cd_gate"]} == {"manual": 1, "automatic": 1}
    # CD's "local-docker" cookbook must NOT dilute the CI-only fallback rate:
    assert agg["rates"]["fallback_rate"] == 50.0            # 1 of 2 CI workflows llm-authored
    # CD runs carry no language/build system, so they don't pollute those charts.
    assert {d["key"] for d in agg["by_build_system"]} == {"maven", "go"}


def test_cd_event_records_kind_and_gate():
    e = telemetry._event(_cd_result(gate="manual approval (production environment)"), 100)
    assert e["kind"] == "cd" and "manual" in e["cd_gate"]


def test_old_cd_event_backfilled_by_cookbook():
    # An event written before the `kind` field existed is recognised as CD by cookbook.
    old = {"status": "opened", "cookbook": "local-docker", "pr_number": 3}
    assert telemetry._kind(old) == "cd"
    assert telemetry.aggregate([old])["totals"]["cd_runs"] == 1


def test_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("CI_BOOTSTRAP_DATA_DIR", str(tmp_path))
    telemetry.record(_result(), 1500)
    c = TestClient(app)
    data = c.get("/telemetry/data").json()
    assert data["totals"]["runs"] == 1
    html = c.get("/dashboard").text
    assert "cicd-bootstrap telemetry" in html and "/telemetry/data" in html
