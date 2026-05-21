#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=${DEBIAN_FRONTEND:-noninteractive}

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y --no-install-recommends \
    python3-pip \
    python3-venv
else
  echo "[bootstrap_env] apt-get not found; please install python3-pip and python3-venv manually." >&2
  exit 1
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo "[bootstrap_env] done"
echo "Activate with: . .venv/bin/activate"
echo "Run API with: uvicorn main:app --host 0.0.0.0 --port 8000"
echo "Run UI with: streamlit run webui.py"
