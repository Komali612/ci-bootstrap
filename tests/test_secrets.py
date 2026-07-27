"""Offline tests for SonarCloud config + Actions-secret encryption.

The network calls in set_repo_secret aren't exercised here; we test the two
pieces that must be correct on their own: the sealed-box encryption (so GitHub
can actually decrypt it) and the SONAR_ORG config override.
"""

from __future__ import annotations

import base64

from nacl import encoding, public

from ci_bootstrap.contracts import Classification, RepoSnapshot
from ci_bootstrap.generate import generate
from ci_bootstrap.github import _seal


def _snap(name="demo", owner="acme"):
    return RepoSnapshot(
        repo_url=f"https://github.com/{owner}/{name}", owner=owner, name=name,
        default_branch="main", tree=["pom.xml"],
    )


def _cls():
    return Classification(language="java", build_system="maven",
                          test_command="mvn -B verify", confidence=1.0, method="test")


def test_seal_is_decryptable_by_the_matching_private_key():
    # Simulate GitHub's side: it holds the private key and must be able to
    # decrypt what _seal produced from the public key.
    sk = public.PrivateKey.generate()
    public_key_b64 = sk.public_key.encode(encoder=encoding.Base64Encoder).decode()

    sealed_b64 = _seal(public_key_b64, "my-sonar-token-value")

    opened = public.SealedBox(sk).decrypt(base64.b64decode(sealed_b64))
    assert opened.decode() == "my-sonar-token-value"


def test_sonar_org_comes_from_config_when_set(monkeypatch):
    monkeypatch.setenv("SONAR_ORG", "my-fixed-org")
    wf = generate(_cls(), _snap(owner="Acme")).content
    assert "my-fixed-org" in wf                     # config value baked in
    assert "organization=Acme" not in wf            # not derived from the owner


def test_sonar_org_falls_back_to_owner_when_unset(monkeypatch):
    monkeypatch.delenv("SONAR_ORG", raising=False)
    wf = generate(_cls(), _snap(owner="Acme")).content
    assert "acme" in wf                             # owner, lowercased
