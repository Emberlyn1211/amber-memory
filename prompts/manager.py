"""Prompt template manager with YAML loading and Jinja2 rendering.

Simplified from OpenViking's PromptManager — no pydantic, no threading lock,
just load YAML + render Jinja2.
"""

import threading
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from jinja2 import Template


class PromptManager:
    """Manages prompt templates with caching and Jinja2 rendering."""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or (Path(__file__).parent / "templates")
        self._cache: Dict[str, dict] = {}
        self._lock = threading.RLock()

    def load_template(self, prompt_id: str) -> dict:
        """Load a prompt template by dotted ID (e.g. 'compression.memory_extraction')."""
        if prompt_id in self._cache:
            return self._cache[prompt_id]

        parts = prompt_id.split(".")
        category = parts[0]
        name = "_".join(parts[1:])
        file_path = self.templates_dir / category / f"{name}.yaml"

        if not file_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        with self._lock:
            self._cache[prompt_id] = data
        return data

    def render(self, prompt_id: str, variables: Optional[Dict[str, Any]] = None) -> str:
        """Render a prompt template with variable substitution."""
        data = self.load_template(prompt_id)
        variables = variables or {}

        # Apply defaults from variable definitions
        for var_def in data.get("variables", []):
            name = var_def.get("name")
            if name and name not in variables and "default" in var_def:
                variables[name] = var_def["default"]

        # Truncate to max_length if specified
        for var_def in data.get("variables", []):
            name = var_def.get("name")
            max_len = var_def.get("max_length")
            if name and max_len and isinstance(variables.get(name), str):
                variables[name] = variables[name][:max_len]

        template = Template(data["template"])
        return template.render(**variables)

    def get_llm_config(self, prompt_id: str) -> Dict[str, Any]:
        data = self.load_template(prompt_id)
        return data.get("llm_config", {})


# Global singleton
_manager: Optional[PromptManager] = None


def get_manager() -> PromptManager:
    global _manager
    if _manager is None:
        _manager = PromptManager()
    return _manager


def render_prompt(prompt_id: str, variables: Optional[Dict[str, Any]] = None) -> str:
    """Convenience: render a prompt using the global singleton."""
    return get_manager().render(prompt_id, variables)
