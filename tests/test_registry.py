"""Tests for the ModelRegistry."""

# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=no-value-for-parameter,protected-access

from unittest.mock import MagicMock

from netlistio.ingestor.registry import ModelRegistry
from netlistio.models.generic import Port
from netlistio.models.spice import Resistor, Subckt


class TestModelRegistry:
    def test_resolves_static_primitive(self):
        r = Resistor()
        registry = ModelRegistry(static_primitives={"resistor": r})
        assert registry.resolve_model("resistor") is r

    def test_resolves_case_insensitive(self):
        r = Resistor()
        registry = ModelRegistry(static_primitives={"resistor": r})
        assert registry.resolve_model("RESISTOR") is r

    def test_resolves_static_macro(self):
        sub = Subckt(name="inv", ports=(Port("in"), Port("out")))
        registry = ModelRegistry(static_macros={"inv": sub})
        assert registry.resolve_model("inv") is sub

    def test_returns_none_for_unknown(self):
        registry = ModelRegistry()
        assert registry.resolve_model("no_such_model") is None

    def test_caches_hit(self):
        r = Resistor()
        registry = ModelRegistry(static_primitives={"resistor": r})
        first = registry.resolve_model("resistor")
        second = registry.resolve_model("resistor")
        assert first is second
        assert "resistor" in registry._resolved_cache

    def test_caches_miss(self):
        registry = ModelRegistry()
        registry.resolve_model("nonexistent")
        assert "nonexistent" in registry._resolved_cache
        assert registry._resolved_cache["nonexistent"] is None

    def test_primitive_checked_before_macro(self):
        r = Resistor()
        sub = Subckt(name="resistor", ports=())
        registry = ModelRegistry(static_primitives={"resistor": r}, static_macros={"resistor": sub})
        result = registry.resolve_model("resistor")
        assert result is r

    def test_register_library_content(self):
        registry = ModelRegistry()
        registry.register_library_content("/path/to/lib.sp", b"content")
        assert "/path/to/lib.sp" in registry.library_content

    def test_dynamic_resolver_called_when_static_miss(self):
        r = Resistor()
        resolver = MagicMock()
        resolver.resolve_model.return_value = r
        registry = ModelRegistry(
            library_content={"lib.sp": b"content"},
            model_resolver=resolver,
        )
        result = registry.resolve_model("my_resistor")
        assert result is r
        resolver.resolve_model.assert_called_once_with("my_resistor", b"content")

    def test_dynamic_resolver_miss_returns_none(self):
        resolver = MagicMock()
        resolver.resolve_model.return_value = None
        registry = ModelRegistry(
            library_content={"lib.sp": b"content"},
            model_resolver=resolver,
        )
        assert registry.resolve_model("unknown") is None
