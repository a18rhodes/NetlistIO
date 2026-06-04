"""End-to-end integration tests against external datasets.

These tests require the SymBench SPICE dataset cloned via scripts/setup_data.sh.
Run with: pytest --integration
"""

# pylint: disable=missing-class-docstring,missing-function-docstring
# pylint: disable=broad-exception-caught,protected-access

from pathlib import Path

import pytest

from netlistio.ingestor.reader import SpiceReader

DATA_DIR = Path(__file__).parent / "data" / "foundry"


@pytest.mark.integration
class TestSymBenchDataset:
    def _all_spice_files(self):
        if not DATA_DIR.exists():
            pytest.skip("SymBench data not available — run scripts/setup_data.sh")
        return sorted(DATA_DIR.rglob("*.sp")) + sorted(DATA_DIR.rglob("*.spice"))

    def test_dataset_present(self):
        assert DATA_DIR.exists(), "Run scripts/setup_data.sh to populate test data"

    def test_all_files_parse_without_exception(self):
        reader = SpiceReader()
        files = self._all_spice_files()
        assert files, "No .sp files found in SymBench dataset"
        failures = []
        for sp_file in files[:50]:
            try:
                reader.read(sp_file, num_workers=1)
            except Exception as exc:
                failures.append((sp_file.name, str(exc)))
        assert not failures, f"Parse failures: {failures}"

    def test_parsed_netlists_have_macros_or_top_instances(self):
        # Model-only library files (.param + .include chains) legitimately produce
        # no subcircuits. Assert that the majority of files have parseable content.
        reader = SpiceReader()
        files = self._all_spice_files()[:20]
        with_content = 0
        for sp_file in files:
            nl = reader.read(sp_file, num_workers=1)
            if nl.macros or nl.top_instances:
                with_content += 1
        assert with_content >= 10, f"Only {with_content}/20 files had parseable circuit content"
