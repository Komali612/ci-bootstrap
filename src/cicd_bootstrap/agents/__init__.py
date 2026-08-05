"""Two separate agents that split the pipeline work.

Rather than one service doing everything, the tool now exposes two independent
agents that a user runs in sequence:

* ``ci_agent``  — creates the CI pipeline (build, test, scan, push the image).
* ``cd_agent``  — once CI has built the image, this picks it up and creates the
  CD (deploy) pipeline.

Each is its own FastAPI app (run them on separate ports). They share the engine
in :mod:`cicd_bootstrap.core` and the telemetry store, so one dashboard shows both.
"""
