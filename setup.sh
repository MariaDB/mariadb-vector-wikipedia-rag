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
ollama pull bge-m3 >/dev/null

if [ "$1" = "--local" ]; then
  echo "3/4  Tables in your own MariaDB"
  .venv/bin/python -c "
from common import connect
con = connect(); cur = con.cursor()
sql = ''.join(l for l in open('schema.sql') if not l.lstrip().startswith('--'))
for statement in sql.split(';'):
    if statement.strip(): cur.execute(statement)"
else
  echo "3/4  MariaDB in Docker"
  docker compose up -d --wait
fi

echo "4/4  Articles, categories and vectors (downloads 110 MB the first time)"
.venv/bin/python load.py --vectors

echo
echo "Ready. Start the search page:  .venv/bin/python app.py   then open http://localhost:8000"
