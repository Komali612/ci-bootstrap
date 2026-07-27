"""Optional CLI wrapper. The service is the primary interface; this is handy
for local runs and testing.

    ci-bootstrap https://github.com/owner/repo        # classify, generate, open PR
    ci-bootstrap https://github.com/owner/repo --no-pr # generate only, print the YAML
    ci-bootstrap --serve [--host H] [--port P]         # run the HTTP service
"""

from __future__ import annotations

import argparse
import sys

from .core import bootstrap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ci-bootstrap", description="Bootstrap CI into a repo.")
    parser.add_argument("repo_url", nargs="?", help="GitHub repository URL")
    parser.add_argument("--no-pr", action="store_true", help="generate the workflow but don't open a PR")
    parser.add_argument("--llm-fallback", action="store_true",
                        help="if no cookbook matches, let the LLM author the cookbook fields")
    parser.add_argument("--serve", action="store_true", help="run the HTTP service instead")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.serve:
        import uvicorn

        uvicorn.run("ci_bootstrap.service:app", host=args.host, port=args.port)
        return 0

    if not args.repo_url:
        parser.error("provide a repo_url, or use --serve")

    result = bootstrap(args.repo_url, open_pr_flag=not args.no_pr, allow_llm_fallback=args.llm_fallback)

    if result.classification:
        c = result.classification
        print(f"classified: {c.language} / {c.build_system} (test: {c.test_command!r}) "
              f"[{c.method}, confidence {c.confidence:.2f}]")
    if result.workflow and result.workflow.llm_authored:
        print("cookbook: LLM-authored (no built-in cookbook for this stack) — review before merging")
    if result.workflow and (args.no_pr or result.status != "opened"):
        print(f"\n--- {result.workflow.path} (cookbook: {result.workflow.cookbook}) ---")
        print(result.workflow.content)

    print(f"\nstatus: {result.status} -- {result.message}")
    if result.pr_url:
        print(f"PR: {result.pr_url}")
    return 0 if result.status in ("opened", "generated") else 1


if __name__ == "__main__":
    sys.exit(main())
