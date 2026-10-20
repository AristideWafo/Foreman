#!/usr/bin/env bash
# Déploie un projet sur un serveur qui héberge déjà Traefik (conteneur), Grafana, cAdvisor, etc.
# Chaque projet vit dans /opt/<projet> ; Traefik le détecte par les labels de compose.custom.yaml.
#
# Usage direct :
#   deploy-custom.sh [options] [<projet>] <image@sha256:digest>
# Usage par SSH (clé limitée par command="...") : SSH_ORIGINAL_COMMAND="deploy [options] [<projet>] <image>"
#
# Un seul argument positionnel = l'image ; le projet vaut alors $FOREMAN_PROJECT (défaut : foreman).
# Cela garde la forme `deploy <image>` utilisée par .github/workflows/deploy.yml.
# Par SSH, SSH_ORIGINAL_COMMAND prime : les options doivent être dans la commande `deploy ...`.
#
# Options : --with-db (PostgreSQL du projet), --dry-run (n'agit pas), -h/--help.
# Entrées non fiables : tout est validé avant d'agir, rien n'est évalué.
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/opt}"
DEFAULT_PROJECT="${FOREMAN_PROJECT:-foreman}"
WAIT_TIMEOUT="${DEPLOY_WAIT_TIMEOUT:-120}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_TEMPLATE="${COMPOSE_TEMPLATE:-${SCRIPT_DIR}/compose.custom.yaml}"

PROJECT_RE='^[a-z0-9][a-z0-9-]{1,40}$'
IMAGE_RE='^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'

die()  { echo "erreur : $1" >&2; exit "${2:-2}"; }
info() { echo "==> $*"; }
usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# --- Arguments (SSH_ORIGINAL_COMMAND prime : c'est l'unique entrée d'une clé restreinte) ---
if [[ -n "${SSH_ORIGINAL_COMMAND:-}" ]]; then
  read -r -a raw <<<"$SSH_ORIGINAL_COMMAND"
  [[ "${raw[0]:-}" == "deploy" ]] || die "commande refusée"
  args=("${raw[@]:1}")
else
  args=("$@")
fi

WITH_DB=0
DRY_RUN=0
positional=()
for a in "${args[@]}"; do
  case "$a" in
    --with-db) WITH_DB=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage; exit 0 ;;
    -*)        die "option inconnue : $a" ;;
    *)         positional+=("$a") ;;
  esac
done

case "${#positional[@]}" in
  1) PROJECT="$DEFAULT_PROJECT"; IMAGE="${positional[0]}" ;;
  2) PROJECT="${positional[0]}"; IMAGE="${positional[1]}" ;;
  *) usage >&2; exit 2 ;;
esac

[[ "$PROJECT" =~ $PROJECT_RE ]] || die "nom de projet invalide (a-z, 0-9, tirets)"
[[ "$IMAGE" =~ $IMAGE_RE ]]     || die "image invalide : un digest ghcr.io/...@sha256:<64 hex> est requis"

APP_DIR="${DEPLOY_ROOT}/${PROJECT}"

# --- Plan (dry-run) -----------------------------------------------------------------------
if [[ "$DRY_RUN" -eq 1 ]]; then
  info "dry-run : rien n'est modifié"
  echo "projet      : ${PROJECT}"
  echo "répertoire  : ${APP_DIR}"
  echo "image       : ${IMAGE}"
  echo "PostgreSQL  : $([[ $WITH_DB -eq 1 ]] && echo "oui (requiert POSTGRES_PASSWORD et FOREMAN_DATABASE_URL, hôte db)" || echo non)"
  echo "compose     : ${COMPOSE_TEMPLATE} -> ${APP_DIR}/compose.yaml"
  echo "étapes      : vérifier .env et le réseau Traefik, valider le compose, pull, up --wait, rollback si échec"
  exit 0
fi

# --- Prérequis ----------------------------------------------------------------------------
command -v docker >/dev/null || die "docker introuvable" 69
docker compose version >/dev/null 2>&1 || die "docker compose (v2) introuvable" 69
# `deploy.resources.limits.pids` (compose.custom.yaml) exige Compose >= 2.29.
compose_version="$(docker compose version --short 2>/dev/null || true)"; compose_version="${compose_version#v}"
if [[ "$compose_version" =~ ^([0-9]+)\.([0-9]+) ]]; then
  (( BASH_REMATCH[1] > 2 || (BASH_REMATCH[1] == 2 && BASH_REMATCH[2] >= 29) )) \
    || die "Docker Compose ${compose_version} trop ancien : 2.29 ou plus requis" 69
else
  die "version de Docker Compose illisible" 69
fi
[[ -f "$COMPOSE_TEMPLATE" ]] || die "modèle de compose introuvable : $COMPOSE_TEMPLATE" 66

if [[ -e "$APP_DIR" && ( -L "$APP_DIR" || ! -d "$APP_DIR" ) ]]; then
  die "${APP_DIR} doit être un vrai répertoire (pas un lien)" 66
fi
install -d -m 0750 "$APP_DIR"
cd "$APP_DIR"

# Un seul déploiement à la fois par projet.
exec 9>"${APP_DIR}/.deploy.lock"
flock -n 9 || die "un déploiement est déjà en cours pour ${PROJECT}" 75

[[ -f .env ]] || die "${APP_DIR}/.env manquant : copier .env.deploy.example et le remplir (FOREMAN_DOMAIN, ...)" 66
chmod 0600 .env

# Variables de .env utilisées par le script (lues, jamais évaluées).
env_value() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | sed -e "s/^[\"']//" -e "s/[\"']\$//" || true; }
DOMAIN="$(env_value FOREMAN_DOMAIN)"
TRAEFIK_NETWORK="$(env_value TRAEFIK_NETWORK)"; TRAEFIK_NETWORK="${TRAEFIK_NETWORK:-traefik}"
[[ -n "$DOMAIN" ]] || die "FOREMAN_DOMAIN absent de ${APP_DIR}/.env" 66
[[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]] || die "FOREMAN_DOMAIN invalide" 66

# Authentification : un seul interrupteur, FOREMAN_AUTH_MODE. En `session` (cible, #228) l'application
# authentifie elle-même et Traefik n'ajoute aucun basicAuth. Dans les autres modes (retour arrière
# `proxy_header`, essai `none`), le basicAuth reste OBLIGATOIRE : `utilisateur:hash` (htpasswd), mot de
# passe en clair refusé. Le site ne peut donc pas être publié ouvert par oubli.
AUTH_MODE="$(env_value FOREMAN_AUTH_MODE)"
AUTH_USERS="$(env_value FOREMAN_BASIC_AUTH_USERS)"
if [[ "$AUTH_MODE" == "session" ]]; then
  [[ -z "$AUTH_USERS" ]] || die "FOREMAN_BASIC_AUTH_USERS doit être retiré de ${APP_DIR}/.env en mode session (double authentification)" 66
  [[ "$(env_value FOREMAN_PUBLIC_URL)" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?/?$ ]] \
    || die "FOREMAN_PUBLIC_URL absent ou non HTTPS dans ${APP_DIR}/.env (https://<domaine>, voir docs/DEPLOYMENT.md)" 66
  [[ "$(env_value FOREMAN_COOKIE_SECURE)" != "0" ]] || die "FOREMAN_COOKIE_SECURE=0 interdit en déploiement" 66
  # Sans cela uvicorn ne fait confiance qu'à 127.0.0.1 : request.client serait l'IP de Traefik (rate-limit commun).
  FWD="$(env_value FORWARDED_ALLOW_IPS)"
  [[ -n "$FWD" && "$FWD" != *'*'* && "$FWD" != "127.0.0.1" ]] \
    || die "FORWARDED_ALLOW_IPS doit être le sous-réseau du réseau Traefik, sans '*' (docker network inspect ${TRAEFIK_NETWORK})" 66
else
  [[ -n "$AUTH_USERS" ]] || die "FOREMAN_BASIC_AUTH_USERS absent de ${APP_DIR}/.env (hors FOREMAN_AUTH_MODE=session ; voir docs/DEPLOYMENT.md)" 66
  IFS=',' read -r -a auth_entries <<<"$AUTH_USERS"
  for entry in "${auth_entries[@]}"; do
    [[ "$entry" =~ ^[A-Za-z0-9._-]+:(\$apr1\$|\$2[aby]\$|\{SHA\}) ]] \
      || die "FOREMAN_BASIC_AUTH_USERS doit contenir des mots de passe hachés (utilisateur:\$apr1\$...), pas en clair" 66
  done
fi

docker network inspect "$TRAEFIK_NETWORK" >/dev/null 2>&1 \
  || die "réseau Traefik '${TRAEFIK_NETWORK}' introuvable (docker network ls) ; ajuster TRAEFIK_NETWORK dans .env" 69

if [[ "$WITH_DB" -eq 1 ]]; then
  [[ -n "$(env_value POSTGRES_PASSWORD)" ]] || die "POSTGRES_PASSWORD absent de ${APP_DIR}/.env (requis avec --with-db)" 66
  # L'application doit viser le service « db » du compose ; sinon elle retomberait en mémoire sans erreur.
  # Compose lit le .env plus largement que `env_value` (export, indentation, ${VAR}, doublons) :
  # on refuse tout ce qui rendrait les deux lectures divergentes. Les valeurs ne sont jamais affichées.
  [[ "$(grep -cE '^[[:space:]]*(export[[:space:]]+)?FOREMAN_DATABASE_URL=' .env || true)" == "1" ]] \
    || die "FOREMAN_DATABASE_URL doit apparaître exactement une fois dans ${APP_DIR}/.env, sous la forme NOM=valeur" 66
  DB_URL="$(env_value FOREMAN_DATABASE_URL)"
  db_url_re='^postgresql(\+psycopg)?://([^:@/]+):([^@/:$]+)@db:[0-9]+/([A-Za-z0-9_]+)$'
  [[ "$DB_URL" =~ $db_url_re ]] \
    || die "FOREMAN_DATABASE_URL invalide dans ${APP_DIR}/.env (postgresql://utilisateur:mot_de_passe@db:5432/base, sans \$ ; voir docs/DEPLOYMENT.md)" 66
  # Cohérence avec POSTGRES_* (valeurs non affichées). Sans `%`, l'URL n'est pas encodée : comparaison directe.
  if [[ "$DB_URL" != *%* ]]; then
    url_user="${BASH_REMATCH[2]}"; url_password="${BASH_REMATCH[3]}"; url_db="${BASH_REMATCH[4]}"
    pg_user="$(env_value POSTGRES_USER)"; pg_db="$(env_value POSTGRES_DB)"
    [[ "$url_user" == "${pg_user:-foreman}" ]] || die "l'utilisateur de FOREMAN_DATABASE_URL diffère de POSTGRES_USER" 66
    [[ "$url_password" == "$(env_value POSTGRES_PASSWORD)" ]] || die "le mot de passe de FOREMAN_DATABASE_URL diffère de POSTGRES_PASSWORD" 66
    [[ "$url_db" == "${pg_db:-foreman}" ]] || die "la base de FOREMAN_DATABASE_URL diffère de POSTGRES_DB" 66
  fi
  export COMPOSE_PROFILES="db"
fi

# --- Compose ------------------------------------------------------------------------------
cp "$COMPOSE_TEMPLATE" compose.yaml
chmod 0640 compose.yaml

compose() { docker compose -p "$PROJECT" --env-file .env -f compose.yaml "$@"; }
export PROJECT FOREMAN_DOMAIN="$DOMAIN"

previous="$(cat .current-image 2>/dev/null || true)"

export FOREMAN_IMAGE="$IMAGE"
info "validation du compose"
compose config -q

info "récupération de l'image"
compose pull

# Sauvegarde avant `up` (une migration peut empêcher l'ancienne image de redémarrer : voir docs/DEPLOYMENT.md).
# Rien à sauvegarder au premier déploiement (le conteneur db n'existe pas encore).
if [[ "$WITH_DB" -eq 1 ]] && compose ps --status running --services 2>/dev/null | grep -qx db; then
  BACKUP_DIR="${DEPLOY_ROOT}/backups"
  install -d -m 0700 "$BACKUP_DIR"
  umask 077
  tmp_dump="$(mktemp "${BACKUP_DIR}/.${PROJECT}.XXXXXX")"
  info "sauvegarde de la base (pg_dump -Fc)"
  # Les identifiants viennent de l'environnement du conteneur : aucun mot de passe en ligne de commande.
  if compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "$tmp_dump"; then
    mv "$tmp_dump" "${BACKUP_DIR}/${PROJECT}-$(date +%Y%m%d-%H%M%S).dump"
    # Rotation : on garde les 5 plus récentes.
    ls -1t "${BACKUP_DIR}/${PROJECT}"-[0-9]*-[0-9]*.dump | tail -n +6 | xargs -r rm -f --
  else
    rm -f -- "$tmp_dump"
    die "sauvegarde de la base échouée : déploiement abandonné" 70
  fi
fi

info "démarrage (attente de la santé, délai ${WAIT_TIMEOUT}s)"
if compose up -d --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT"; then
  [[ -n "$previous" && "$previous" != "$IMAGE" ]] && echo "$previous" > .previous-image
  echo "$IMAGE" > .current-image
  info "déployé : ${IMAGE} sur https://${DOMAIN}"
  compose ps
  exit 0
fi

echo "échec du démarrage ou du contrôle de santé" >&2
compose ps >&2 || true
compose logs --no-color --tail=50 app >&2 || true
if [[ -n "$previous" ]]; then
  info "retour arrière vers ${previous}"
  export FOREMAN_IMAGE="$previous"
  if compose up -d --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT"; then
    echo "retour arrière réussi" >&2
  else
    echo "retour arrière en échec : intervention manuelle requise" >&2
  fi
else
  echo "aucune version précédente : rien vers quoi revenir" >&2
fi
exit 1
