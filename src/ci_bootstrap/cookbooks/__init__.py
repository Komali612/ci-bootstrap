"""Cookbook registry.

Every cookbook is declared as data in ``cookbooks.yaml`` and loaded when
``base`` is imported. To add a new language, edit ``cookbooks.yaml`` -- there is
no per-language Python module to write.
"""

from __future__ import annotations

from .base import Cookbook, get, load, register, render_workflow, supported

__all__ = ["Cookbook", "get", "load", "register", "render_workflow", "supported"]
