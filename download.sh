#!/usr/bin/env bash

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# ------------------------------------------------------------------
# 1. Embedding model (used for memory/semantic search vector encoding)
# ------------------------------------------------------------------

MODEL_URL="https://huggingface.co/xenova/all-MiniLM-L6-v2/resolve/main/onnx/model.onnx"
TOKENIZER_URL="https://huggingface.co/xenova/all-MiniLM-L6-v2/resolve/main/tokenizer.json"

if [ -f "all-MiniLM-L6-v2.onnx" ]; then
    echo "all-MiniLM-L6-v2.onnx already exists, skipping."
else
    echo "Downloading all-MiniLM-L6-v2.onnx..."
    curl -L --progress-bar -o "all-MiniLM-L6-v2.onnx" "$MODEL_URL"
fi

if [ -f "tokenizer.json" ]; then
    echo "tokenizer.json already exists, skipping."
else
    echo "Downloading tokenizer.json..."
    curl -L --progress-bar -o "tokenizer.json" "$TOKENIZER_URL"
fi

# ------------------------------------------------------------------
# 2. Local chat models -- SLM and Offline_LLM
#
# Model choice is LOCKED in config/models.json (single source of
# truth -- core/orchestration/llm_bridge.py reads the exact same file,
# so this script can never silently drift out of sync with what the
# code actually loads). Two SEPARATE models, two SEPARATE jobs:
#
#   models/SLM/         -- small, fast model for narrow classification
#                          only (blueprint SLM tier). Chosen for speed:
#                          real-device benchmarks put this class of
#                          model at roughly 2x the tokens/sec of the
#                          Offline_LLM model below.
#   models/Offline_LLM/ -- full offline conversational fallback, used
#                          only when Groq (online) is unavailable.
#                          Previously a 3B model that measured 40-120s
#                          per reply on CPU-only Termux/PRoot -- this
#                          config now points at a 1.5B model instead,
#                          real-device benchmarks suggest roughly 2x
#                          faster for the same reason.
#
# This script reads config/models.json with python3 (guaranteed
# present in this project) rather than requiring jq, which isn't
# always installed on Termux.
# ------------------------------------------------------------------

read_model_config() {
    # $1 = top-level key ("slm" or "offline_llm"), $2 = field name
    python3 -c "
import json, sys
with open('config/models.json', 'r', encoding='utf-8') as f:
    cfg = json.load(f)
print(cfg['$1']['$2'])
"
}

download_local_model() {
    local role_key="$1"       # "slm" or "offline_llm"
    local subdir filename url dest

    subdir="$(read_model_config "$role_key" subdir)"
    filename="$(read_model_config "$role_key" model_filename)"
    url="$(read_model_config "$role_key" download_url)"
    dest="models/${subdir}/${filename}"

    mkdir -p "models/${subdir}"
    if [ -f "$dest" ]; then
        echo "$dest already exists, skipping."
    else
        echo "Downloading $dest ..."
        curl -L --progress-bar -o "$dest" "$url"
    fi
}

download_local_model "slm"
download_local_model "offline_llm"

echo "Download completed successfully."
