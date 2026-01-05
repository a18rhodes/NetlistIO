#!/bin/bash
# scripts/setup_data.sh

# Ensure the directory exists
mkdir -p tests/data

# Clone SymBench (The Variety Pack)
if [ ! -d "tests/data/foundry" ]; then
    echo "Cloning SymBench..."
    git clone --depth 1 https://github.com/symbench/spice-datasets.git tests/data/foundry
else
    echo "SymBench already exists. Skipping."
fi
