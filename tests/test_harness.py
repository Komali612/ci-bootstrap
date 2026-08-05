"""Deterministic tests for the Harness CD generator (no network / no account)."""

import yaml

from cicd_bootstrap.harness import (
    build_deploy_script,
    build_pipeline,
    identifier,
    render_notify_workflow,
)


def test_identifier_sanitizes():
    assert identifier("cicd-test-full") == "cicd_test_full"
    assert identifier("9lives").startswith("_")   # can't start with a digit


def test_pipeline_yaml_is_valid_and_deploys_on_delegate():
    p = build_pipeline("Owner", "my-app", 8080, auto_deploy=True, org="default", project="default_project")
    parsed = yaml.safe_load(yaml.dump(p))          # round-trips as valid YAML
    pipe = parsed["pipeline"]
    assert pipe["identifier"] == "deploy_my_app"
    assert pipe["variables"][0]["name"] == "imageTag"
    stage = pipe["stages"][0]["stage"]
    assert stage["type"] == "Custom"
    step = stage["spec"]["execution"]["steps"][0]["step"]
    assert step["spec"]["onDelegate"] is True
    assert step["spec"]["delegateSelectors"] == ["laptop"]


def test_approval_stage_toggles_with_auto_deploy():
    manual = build_pipeline("Owner", "app", 80, auto_deploy=False, org="default", project="p")
    auto = build_pipeline("Owner", "app", 80, auto_deploy=True, org="default", project="p")
    assert [s["stage"]["type"] for s in manual["pipeline"]["stages"]] == ["Approval", "Custom"]
    assert [s["stage"]["type"] for s in auto["pipeline"]["stages"]] == ["Custom"]


def test_deploy_script_pulls_ghcr_and_health_checks_via_host():
    s = build_deploy_script("Owner", "My-App", 8091)
    assert "ghcr.io/owner/my-app:" in s              # lowercased image ref
    assert "<+pipeline.variables.imageTag>" in s     # tag comes from the pipeline input
    assert 'PORT="8091"' in s                         # the detected port
    assert "host.docker.internal:$PORT" in s          # health check reaches the host, not the delegate
    assert "Rolling back" in s                        # rollback path present


def test_notify_workflow_pings_harness_after_ci():
    w = render_notify_workflow("CI", "main")
    assert "HARNESS_WEBHOOK_URL" in w                 # uses the repo secret
    assert "workflow_run" in w and "head_sha" in w    # fires after CI, sends the built SHA
    assert 'workflows: ["CI"]' in w
