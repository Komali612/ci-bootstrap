"""Cookbook registry.

Importing this package registers every cookbook. To add a new language, create
a module here that calls `register(...)` and add it to the import list below --
that is the only wiring needed.
"""

from __future__ import annotations

from .base import Cookbook, get, register, render_workflow, supported

# Import each cookbook module for its registration side effect.
from . import java_maven  # noqa: F401  (java / maven)
from . import dotnet      # noqa: F401  (.net / csharp)

__all__ = ["Cookbook", "get", "register", "render_workflow", "supported"]
