#!/bin/sh
# Set everything up in one go: Python packages, the embedding model, MariaDB in Docker, and the
# data with ready-made vectors. Takes a few minutes. Then:  .venv/bin/python app.py
#
#   ./setup.sh           # MariaDB in Docker (port 3307)
#   ./setup.sh --local   # use a MariaDB you already run; set DB_PORT etc. in .env first
set -e
cd "$(dirname "$0")"

need() { command -v "$1" >/dev/null || { echo "Missing: $1 — $2"; exit 1; }; }
need python3 "install Python 3.11 or later"
need ollama  "install from https://ollama.com/download"
[ "$1" = "--local" ] || need docker "install Docker Desktop, Colima or OrbStack, or run ./setup.sh --local"

echo "1/4  Python packages"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

echo "2/4  Embedding model bge-m3 (1.2 GB, once)"
ollama pull bge-m3 >/dev/null 2>&1 || { echo "ollama pull failed. Is Ollama running? Start it from the menu bar or with: ollama serve"; exit 1; }

if [ "$1" != "--local" ]; then
  echo "3/4  MariaDB in Docker, and the tables"
  docker compose up -d --wait
else
  echo "3/4  The tables, in your own MariaDB"
fi
.venv/bin/python create_tables.py

echo "4/4  Articles, categories and vectors (downloads 110 MB the first time)"
.venv/bin/python load.py --vectors

echo
echo "Ready. Start the search page:  .venv/bin/python app.py   then open http://localhost:8000"
