#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/../tests/data"
mkdir -p "${DATA_DIR}"
if [ -d "${DATA_DIR}/foundry/sram/.git" ]; then
    echo "SRAM foundry data already present. Skipping clone."
    exit 0
fi
mkdir -p "${DATA_DIR}/foundry"
echo "Cloning vsdsram_sky130 SPICE dataset..."
git clone --depth 1 https://github.com/vsdip/vsdsram_sky130.git "${DATA_DIR}/foundry/sram"
echo "vsdsram_sky130 cloned successfully to ${DATA_DIR}/foundry/sram"
