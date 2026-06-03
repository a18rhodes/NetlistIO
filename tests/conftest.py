"""Shared pytest configuration and fixtures."""

# pylint: disable=missing-function-docstring,import-outside-toplevel,redefined-outer-name

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption("--integration", action="store_true", default=False, help="Run integration tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires external data (run with --integration)")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--integration"):
        skip = pytest.mark.skip(reason="pass --integration to run")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def fixture_path():
    def _get(name: str) -> Path:
        return FIXTURES_DIR / name

    return _get


@pytest.fixture
def open_fixture_mmap(fixture_path):
    from netlistio.ingestor.common import open_mmap

    def _open(name: str):
        return open_mmap(fixture_path(name))

    return _open


@pytest.fixture
def tmp_spice(tmp_path):
    def _write(content: str) -> Path:
        p = tmp_path / "test.sp"
        p.write_text(content)
        return p

    return _write


@pytest.fixture(autouse=True)
def _patch_plt_show(monkeypatch):
    try:
        import matplotlib.pyplot as plt

        monkeypatch.setattr(plt, "show", lambda: None)
    except ImportError:
        pass
