#!/usr/bin/env bash
# Seul programme que la clé SSH de déploiement peut exécuter (authorized_keys: command="...").
# Usage (via SSH_ORIGINAL_COMMAND) : deploy <image@sha256:digest>
set -euo pipefail

APP_DIR="${FOREMAN_APP_DIR:-/opt/foreman}"
read -r action image _ <<<"${SSH_ORIGINAL_COMMAND:-$*}"

[[ "${action:-}" == "deploy" ]] || { echo "commande refusée" >&2; exit 2; }
[[ "${image:-}" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$ ]] || { echo "image invalide (digest requis)" >&2; exit 2; }

cd "$APP_DIR"
previous="$(cat .current-image 2>/dev/null || true)"

export FOREMAN_IMAGE="$image"
docker compose pull app
docker compose up -d --remove-orphans

healthy() {
  for _ in 1 2 3; do
    sleep 10
    docker compose exec -T app python -c \
      "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)" \
      || return 1
  done
}

if healthy; then
  echo "$image" > .current-image
  echo "déployé : $image"
else
  echo "échec du contrôle de santé" >&2
  if [[ -n "$previous" ]]; then
    export FOREMAN_IMAGE="$previous"
    docker compose up -d
    echo "retour arrière : $previous" >&2
  fi
  exit 1
fi
