"""Provision the SonarCloud project so a repo's FIRST scan doesn't fail.

A brand-new repo has no SonarCloud project yet, so the first CI scan fails --
either "project not found" or SonarCloud's "you are running CI analysis while
Automatic Analysis is enabled" conflict. Creating the project via the API up
front fixes both at once:

  * the project exists, so the scan has somewhere to report, and
  * a project created through the API has Automatic Analysis OFF by default,
    which is exactly what CI-based analysis needs.

This is idempotent: creating a project that already exists is treated as fine,
so re-bootstrapping the same repo is a no-op here.
"""

from __future__ import annotations

import httpx

API = "https://sonarcloud.io/api"


class SonarError(Exception):
    """Raised when the SonarCloud project can't be provisioned."""


def provision_project(org: str, project_key: str, name: str, token: str) -> str:
    """Create the SonarCloud project if it doesn't already exist.

    Returns "created" (new) or "exists" (already there). Raises SonarError on any
    other failure. The token authenticates as the SonarCloud org; it is passed as
    HTTP basic-auth username (SonarCloud's scheme) and never logged.
    """
    resp = httpx.post(
        f"{API}/projects/create",
        auth=(token, ""),
        data={"organization": org, "project": project_key, "name": name},
        timeout=30,
    )
    if resp.status_code == 200:
        return "created"
    if resp.status_code == 400 and "already exists" in resp.text.lower():
        return "exists"
    raise SonarError(f"create SonarCloud project {project_key!r} failed: {resp.status_code} {resp.text[:200]}")
