# CHANGELOG


## v0.1.0 (2026-06-04)

### Bug Fixes

- Chown /opt/poetry-venvs to vscode in dev stage so poetry install works without sudo
  ([`ad6e038`](https://github.com/a18rhodes/NetlistIO/commit/ad6e038e8a99b3a0d0b896793b63d96b7c3b2b49))

- Install torch CPU in CI and skip integration tests gracefully when torch absent
  ([`53b4849`](https://github.com/a18rhodes/NetlistIO/commit/53b48495a46219d6d58ae245518e027c0b2f1319))

All three workflows (CI test, CI integration, Release) now install torch and torch_geometric from
  the CPU wheel index after poetry install, so the to_pyg test suite and coverage requirement pass.
  Cache keys updated with -torch-cpu suffix to avoid collisions with prior caches that did not
  include torch.

test_align_graphs.py uses pytest.importorskip so the module is skipped rather than erroring on
  environments without torch.

- Invalid workdir
  ([`ce82b44`](https://github.com/a18rhodes/NetlistIO/commit/ce82b44f6c72e54598d4cc3318ef41e787eabe1d))

- Make e2e file ordering deterministic and tolerate model-only netlists
  ([`c079c07`](https://github.com/a18rhodes/NetlistIO/commit/c079c07b0fc0723b9112b69c37d7cd1da9447941))

rglob() traversal order is filesystem-dependent; CI ext4 vs WSL2 produced different first-20 slices,
  some of which contained model library files that legitimately yield no subcircuits. Sort the file
  list for consistent ordering and replace the per-file assertion with a majority threshold.

- Move containerEnv to the right place, add dotenv.
  ([`0a63988`](https://github.com/a18rhodes/NetlistIO/commit/0a6398832b0a3b5597eac21338ee11b715b4ad84))

- Run semantic-release version before publish for v9 compatibility
  ([`0e92ae0`](https://github.com/a18rhodes/NetlistIO/commit/0e92ae069efc9c0f67c8e7d4955662d233991654))

v9 split the old publish monolith into separate version and publish commands. publish alone has no
  tag to attach artifacts to and fails.

- Skip ALIGN integration tests when torch is not installed
  ([`a080723`](https://github.com/a18rhodes/NetlistIO/commit/a0807230a1fe3b4baaca983679e8ba6a04402a72))

pytest.importorskip causes the module to be skipped rather than failing at collection time on CI
  environments without torch. Reordered imports to satisfy pylint's wrong-import-position check.

- Switch e2e dataset to vsdsram_sky130, exclude tests/data from tooling
  ([`7709d54`](https://github.com/a18rhodes/NetlistIO/commit/7709d54d55d42a27e25c7af4c2d1bb29a9f7a1b1))

The ALIGN-public clone was the wrong data source for e2e tests and introduced a full Python
  toolchain dependency we don't want. Switch to the vsdsram_sky130 SRAM dataset (Apache 2.0) which
  was the original intent — real SPICE netlists with no tooling dependency.

Tool exclusions (black extend-exclude, isort skip_glob, pylint ignore-paths, pytest norecursedirs)
  prevent linters and the test runner from descending into gitignored external clones under
  tests/data.

- Use official git env vars and don't set global opts
  ([`a333121`](https://github.com/a18rhodes/NetlistIO/commit/a3331216d92753f3a40f3695f3ad3f8f41ec8325))

### Chores

- Add CI and release workflows for automated testing and deployment
  ([`6012512`](https://github.com/a18rhodes/NetlistIO/commit/601251229c3e5281dc2344a36250dc2463bfd2bd))

- Introduced a CI workflow to run tests, format checks, and linting on every push and pull request.
  - Added a release workflow to handle automated releases on pushes to the main branch, including
  semantic release functionality. - Configured Python 3.11 environment and integrated Poetry for
  dependency management.

- Add torch/PyG to Docker image and tighten CI gates
  ([`5b4fb1a`](https://github.com/a18rhodes/NetlistIO/commit/5b4fb1a2d6d27bbf548dd1a9bddc466fd95f5ff6))

- Dockerfile: install torch and torch_geometric into the Poetry venv via pip after Poetry creates
  it; add TORCH_CUDA_TAG build arg (default cu124) so the image can target CUDA or CPU wheels;
  symlink the venv to /opt/venv for a stable interpreter path; add libgomp1 for OpenMP support -
  devcontainer: update defaultInterpreterPath to /opt/venv/bin/python - CI: raise pylint floor to
  10.0, add --cov-fail-under=100, add nightly integration job that fetches the SymBench dataset and
  runs pytest --integration - release: expand pre-release gate to match CI (pylint + unit coverage +
  integration) - pyproject.toml / poetry.lock: reflect dependency updates

- Bump deps for security vulnerabilities
  ([`cd8467d`](https://github.com/a18rhodes/NetlistIO/commit/cd8467df93c71b94d872a3a2b8e78db048e93eb8))

- Update dependencies and add pylint configuration
  ([`42efb16`](https://github.com/a18rhodes/NetlistIO/commit/42efb1670118386e47870b4b997c3d6063e61a90))

- Changed Python version specification from "~3.11" to "^3.11". - Added new dependencies:
  python-semantic-release and pydot. - Enhanced pylint configuration with design and messages
  control settings. - Updated pytest options for coverage reporting and added markers for
  integration tests. - Configured semantic release settings in pyproject.toml.

- Update poetry.lock and pyproject.toml for dependency management
  ([`014de8c`](https://github.com/a18rhodes/NetlistIO/commit/014de8cc224d038e12d57b534384ee60dcc0bce9))

- Upgraded Poetry version from 2.2.1 to 2.4.1 in poetry.lock. - Added new packages: annotated-types,
  anyio, appnope, argon2-cffi, and arrow with their respective versions and dependencies. - Changed
  Python version specification in pyproject.toml from "^3.11" to "~3.11".

### Documentation

- Add architecture guide, overhaul README, include graph images
  ([`1858f80`](https://github.com/a18rhodes/NetlistIO/commit/1858f802089733d8fc9a75999bbe6b0a02fc6531))

architecture.md covers all five pipeline stages with accurate technical detail: mmap tradeoffs vs
  buffered read, NetConnection list representation, primitive port assignment, PyG feature schema,
  and the GANA structural validation approach.

README removes unsubstantiated claims and competitor comparisons, corrects the install instructions
  (not yet on PyPI), and adds example bipartite and device-projection plots of the five-transistor
  OTA from the ALIGN benchmark suite.

### Features

- Add SPICE parser, linker, bipartite graph builder, and CLI
  ([`b68fce2`](https://github.com/a18rhodes/NetlistIO/commit/b68fce2c1e726818c06cd8e2a9b9a3974e23fa09))

Five-stage pipeline: mmap scanner produces byte-range regions, compiler resolves the include graph
  iteratively, parallel chunk parser extracts instances and declarations, linker resolves models and
  assigns formal ports positionally (including primitive devices), CircuitGraph builds a bipartite
  net/instance graph and projects it to PyG HeteroData.

Notable design decisions: - Instance.nets is list[NetConnection] to preserve duplicate net names
  (e.g. vss vss for tied source/bulk), enabling correct positional port assignment by the linker for
  all device types. - Terminal vocabulary derived automatically from registered Primitive port
  names; expands without changes to the graph builder. - Net type features
  (port/signal/power/ground) and one-hot terminal edge features match the bipartite multigraph
  described in Kunal et al., DATE 2020 (GANA).

- Clean up docker and devcontainers
  ([`e18590b`](https://github.com/a18rhodes/NetlistIO/commit/e18590b95f269755c4df07a939ac9d517a65cde0))

### Refactoring

- Improve setup_data.sh for cloning SymBench datasets
  ([`2fc3f12`](https://github.com/a18rhodes/NetlistIO/commit/2fc3f124431b14afd1558c8a900d74c2cff98690))

- Enhanced error handling with set -euo pipefail. - Updated directory structure for data storage. -
  Changed clone condition to check for existing .git directory. - Improved output messages for
  clarity.

### Testing

- Add full test suite with ALIGN integration fixtures
  ([`f5195fd`](https://github.com/a18rhodes/NetlistIO/commit/f5195fdfad6cbc35a25090a30e4b0a91d90fedd6))

100% line coverage across the library. Test highlights:

- Property-based tests (Hypothesis) on the line parser - Linker tests cover tree-shaking, cycle
  detection, port mismatch warnings, and the new primitive port assignment path - CircuitGraph tests
  cover bipartite and device projections, all to_pyg() feature dimensions, and matplotlib/DOT
  fallback paths - Integration tests (--integration) parse four ALIGN benchmark circuits (telescopic
  OTA, five-transistor OTA, current mirror OTA, cascode current mirror OTA) and assert node counts,
  bipartite topology, net type classification, and 100% named terminal coverage against the GANA
  graph representation

ALIGN fixtures are sourced from ALIGN-analoglayout/ALIGN-public (Apache 2.0) and vendored under
  tests/fixtures/align/.
