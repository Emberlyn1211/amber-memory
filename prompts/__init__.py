"""Prompt template system for Amber Memory.

Adapted from OpenViking's prompt management with Jinja2 + YAML templates.
"""

from .manager import render_prompt, get_manager

__all__ = ["render_prompt", "get_manager"]
