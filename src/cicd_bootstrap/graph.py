"""The CI -> CD orchestration as a LangGraph ``StateGraph``.

Each node is a thin wrapper over an existing deterministic function in
:mod:`cicd_bootstrap.core` (``bootstrap`` / ``wait_for_ci_success`` /
``add_cd_harness``). Expressing the chain as a graph gives us:

* **conditional branching** — stop early if CI fails or the image never builds,
* **checkpointing** — a checkpointer makes a run resumable (e.g. survive a
  restart during the long CI wait),
* **human-in-the-loop** — compile with ``interrupt_before_deploy=True`` to pause
  before the deploy for an approval, then resume.

The nodes resolve their functions on the ``core`` module **at call time**, so
tests that monkeypatch ``core.bootstrap`` etc. keep working, and there's no
import cycle (``core`` imports this module lazily).
"""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from .contracts import BootstrapResult


class ChainState(TypedDict, total=False):
    """State threaded through the graph. Nodes return partial updates."""

    repo_url: str
    token: Optional[str]
    owner: str
    name: str
    allow_llm_fallback: bool
    auto_deploy: bool
    wait_timeout_s: int
    ci: Optional[BootstrapResult]
    image_ready: bool
    cd: Optional[BootstrapResult]
    message: str


def _ci_node(state: ChainState) -> dict:
    """Generate + open + auto-merge the CI PR."""
    from . import core

    ci = core.bootstrap(
        state["repo_url"], open_pr_flag=True, token=state.get("token"),
        allow_llm_fallback=state.get("allow_llm_fallback", False), merge=True,
    )
    out: dict = {"ci": ci}
    if ci.status != "opened":
        out["message"] = f"CI stopped ({ci.status}): {ci.message}"
    elif not ci.merged:
        out["message"] = "CI PR opened but couldn't be auto-merged; merge it yourself, then run CD."
    return out


def _after_ci(state: ChainState) -> str:
    ci = state.get("ci")
    return "wait" if (ci and ci.status == "opened" and ci.merged) else END


def _wait_node(state: ChainState) -> dict:
    """Wait for CI to finish on the default branch and push the image."""
    from . import core

    ci = state.get("ci")
    ready = core.wait_for_ci_success(
        state["owner"], state["name"], (ci.merge_sha or "") if ci else "",
        state.get("token"), timeout_s=state.get("wait_timeout_s", 900),
    )
    out: dict = {"image_ready": ready}
    if not ready:
        out["message"] = (
            "CI didn't finish successfully in time, so no image yet and CD was skipped. "
            "Check the CI run on GitHub, then run CD from the CD agent."
        )
    return out


def _after_wait(state: ChainState) -> str:
    return "cd" if state.get("image_ready") else END


def _cd_node(state: ChainState) -> dict:
    """Provision Harness CD (image gate passes now) and deploy the current image."""
    from . import core

    cd = core.add_cd_harness(
        state["repo_url"], token=state.get("token"),
        auto_deploy=state.get("auto_deploy", True), open_pr_flag=True,
    )
    if cd.status == "opened":
        msg = ("Done — CI built the image and Harness CD is set up: the pipeline is stored in the "
               "repo, the current image was deployed to your laptop, and future CI builds auto-deploy.")
    else:
        msg = f"Image is ready, but Harness CD ended as '{cd.status}': {cd.message}"
    return {"cd": cd, "message": msg}


def build_cicd_graph(checkpointer=None, *, interrupt_before_deploy: bool = False):
    """Compile the CI -> CD graph.

    ``checkpointer`` defaults to an in-memory saver (pass a persistent one for
    cross-restart resume). ``interrupt_before_deploy=True`` pauses the run right
    before the deploy step for a human approval (resume with the same thread id).
    """
    g = StateGraph(ChainState)
    g.add_node("ci", _ci_node)
    g.add_node("wait", _wait_node)
    g.add_node("cd", _cd_node)
    g.add_edge(START, "ci")
    g.add_conditional_edges("ci", _after_ci, {"wait": "wait", END: END})
    g.add_conditional_edges("wait", _after_wait, {"cd": "cd", END: END})
    g.add_edge("cd", END)
    return g.compile(
        checkpointer=checkpointer or MemorySaver(),
        interrupt_before=["cd"] if interrupt_before_deploy else None,
    )
