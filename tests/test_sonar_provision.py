"""Offline tests for SonarCloud project provisioning.

No network: we monkeypatch httpx.post and assert how provision_project maps
responses to created / exists / error. The idempotency case (400 "already
exists") is the important one -- re-bootstrapping a repo must not blow up.
"""

from __future__ import annotations

import pytest

from cicd_bootstrap import sonar


class _Resp:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


def test_provision_returns_created_on_200(monkeypatch):
    monkeypatch.setattr(sonar.httpx, "post", lambda *a, **k: _Resp(200, '{"project":{}}'))
    assert sonar.provision_project("org", "org_repo", "repo", "tok") == "created"


def test_provision_is_idempotent_on_already_exists(monkeypatch):
    body = '{"errors":[{"msg":"Could not create Project, key already exists: org_repo"}]}'
    monkeypatch.setattr(sonar.httpx, "post", lambda *a, **k: _Resp(400, body))
    assert sonar.provision_project("org", "org_repo", "repo", "tok") == "exists"


def test_provision_raises_on_other_errors(monkeypatch):
    monkeypatch.setattr(sonar.httpx, "post", lambda *a, **k: _Resp(403, '{"errors":[{"msg":"Insufficient privileges"}]}'))
    with pytest.raises(sonar.SonarError):
        sonar.provision_project("org", "org_repo", "repo", "tok")
