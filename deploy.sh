#!/usr/bin/env bash
# rsync кода и compose up. .env на сервере не трогает.
set -euo pipefail

cd "$(dirname "$0")"
HOST="${RAGKB_DEPLOY_HOST:-adminai@10.10.1.114}"
KEY="${RAGKB_DEPLOY_KEY:-$HOME/.ssh/ai_server}"
REMOTE="${RAGKB_DEPLOY_DIR:-/opt/ragkb}"
SSH="ssh -i $KEY -o BatchMode=yes"

rsync -az --delete --exclude .git --exclude .env --exclude .venv --exclude node_modules \
  -e "$SSH" ./ "$HOST:$REMOTE/"
$SSH "$HOST" "cd $REMOTE && docker compose up -d --build migrate rag frontend"
