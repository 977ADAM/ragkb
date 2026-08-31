#!/usr/bin/env bash
# Выкладка без домена и без пароля: migrate + rag + frontend на :3000.
# Keycloak не поднимается (профиль idp).
#
# С ноутбука (этот репозиторий → сервер):
#   ./deploy.sh
# На самом сервере, из корня клона:
#   ./deploy.sh --local
# С GitHub: пуш тега v* → .github/workflows/deploy.yml (секрет DEPLOY_SSH_KEY).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
HOST="${RAGKB_DEPLOY_HOST:-adminai@10.10.1.114}"
KEY="${RAGKB_DEPLOY_KEY:-$HOME/.ssh/ai_server}"
REMOTE="${RAGKB_DEPLOY_DIR:-/opt/ragkb}"

write_env() {
  local dest="$1"
  if [[ -f "$dest" ]]; then
    return 0
  fi
  cat >"$dest" <<'EOF'
RAGKB_AUTH_MODE=disabled
RAGKB_ORG_NAME=kb
RAGKB_ORG_ID=kb
RAGKB_LLM_BACKEND=openai
RAGKB_LLM_URL=http://host.docker.internal:8080/v1
RAGKB_EMBEDDING_BACKEND=sentence-transformers
RAGKB_EMBEDDING_MODEL=BAAI/bge-m3
EOF
}

up() {
  docker compose up -d --build migrate rag frontend
  docker compose ps
}

if [[ "${1:-}" == "--local" ]]; then
  cd "$ROOT"
  write_env "$ROOT/.env"
  up
  exit 0
fi

SSH=(ssh -o BatchMode=yes -i "$KEY" "$HOST")
RSYNC=(rsync -az --delete
  --exclude .git
  --exclude .venv
  --exclude node_modules
  --exclude .svelte-kit
  --exclude data/index
  --exclude data/history
  --exclude certs
  --exclude .env
  --exclude .DS_Store
  --exclude '*.pyc'
  --exclude __pycache__
  -e "ssh -o BatchMode=yes -i $KEY")

"${RSYNC[@]}" "$ROOT/" "$HOST:$REMOTE/"
"${SSH[@]}" "mkdir -p '$REMOTE' && cd '$REMOTE' && if [[ ! -f .env ]]; then cat > .env <<'EOF'
RAGKB_AUTH_MODE=disabled
RAGKB_ORG_NAME=kb
RAGKB_ORG_ID=kb
RAGKB_LLM_BACKEND=openai
RAGKB_LLM_URL=http://host.docker.internal:8080/v1
RAGKB_EMBEDDING_BACKEND=sentence-transformers
RAGKB_EMBEDDING_MODEL=BAAI/bge-m3
EOF
fi && docker compose up -d --build migrate rag frontend && docker compose ps"
echo "Интерфейс: http://${HOST#*@}:3000"
