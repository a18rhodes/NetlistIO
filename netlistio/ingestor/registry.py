"""
Dynamic model registry for resolving models from library files.

Provides runtime model resolution from parsed library content,
allowing unknown models to be resolved during the linking phase.
"""

from dataclasses import dataclass, field
from typing import Protocol

from netlistio.models.generic import Macro, Primitive

__all__ = ["ModelRegistry", "ModelResolver"]


class ModelResolver(Protocol):
    """Protocol for model resolution strategies."""

    def resolve_model(self, model_name: str, library_content: bytes) -> Macro | Primitive | None:
        """Attempt to resolve a model from library content."""


@dataclass
class ModelRegistry:
    """
    Dynamic registry for runtime model resolution.

    Combines static primitive definitions with dynamically parsed
    models from library files.
    """

    static_primitives: dict[str, Primitive] = field(default_factory=dict)
    static_macros: dict[str, Macro] = field(default_factory=dict)
    library_content: dict[str, bytes] = field(default_factory=dict)
    model_resolver: ModelResolver | None = None
    _resolved_cache: dict[str, Macro | Primitive | None] = field(default_factory=dict)

    def register_library_content(self, lib_path: str, content: bytes) -> None:
        """Register library content for dynamic resolution."""
        self.library_content[lib_path] = content

    def resolve_model(self, model_name: str) -> Macro | Primitive | None:
        """
        Resolve model by name, checking static definitions first, then libraries.

        :param model_name: Name of model to resolve.
        :return: Resolved model or None if not found.
        """
        model_name_lower = model_name.lower()

        # Check cache first
        if model_name_lower in self._resolved_cache:
            return self._resolved_cache[model_name_lower]

        # Check static primitives
        if model := self.static_primitives.get(model_name_lower):
            self._resolved_cache[model_name_lower] = model
            return model

        # Check static macros
        if model := self.static_macros.get(model_name_lower):
            self._resolved_cache[model_name_lower] = model
            return model

        # Try dynamic resolution from libraries
        if self.model_resolver:
            for content in self.library_content.values():
                if model := self.model_resolver.resolve_model(model_name_lower, content):
                    self._resolved_cache[model_name_lower] = model
                    return model

        # Cache miss result
        self._resolved_cache[model_name_lower] = None
        return None
