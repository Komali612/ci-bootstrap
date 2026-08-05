"""URL parsing -- the only part of ingest that doesn't touch the network."""

from __future__ import annotations

import pytest

from cicd_bootstrap.ingest import IngestError, parse_repo_url


@pytest.mark.parametrize(
    "url,owner,name",
    [
        ("https://github.com/Komali612/java-service", "Komali612", "java-service"),
        ("https://github.com/Komali612/java-service.git", "Komali612", "java-service"),
        ("https://github.com/Komali612/java-service/", "Komali612", "java-service"),
        ("git@github.com:acme/widget.git", "acme", "widget"),
    ],
)
def test_parse_repo_url_ok(url, owner, name):
    assert parse_repo_url(url) == (owner, name)


@pytest.mark.parametrize("url", ["https://gitlab.com/a/b", "not-a-url", "https://github.com/onlyowner"])
def test_parse_repo_url_rejects(url):
    with pytest.raises(IngestError):
        parse_repo_url(url)
