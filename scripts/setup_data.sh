#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/../tests/data"
mkdir -p "${DATA_DIR}"
if [ -d "${DATA_DIR}/foundry/.git" ]; then
    echo "SymBench repository already exists. Skipping clone."
    exit 0
fi
echo "Cloning SymBench SPICE datasets..."
git clone --depth 1 https://github.com/symbench/spice-datasets.git "${DATA_DIR}/foundry"
echo "SymBench cloned successfully to ${DATA_DIR}/foundry"
