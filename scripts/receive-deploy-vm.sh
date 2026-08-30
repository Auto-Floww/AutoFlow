#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_DIR="/home/ubuntu/autoflow"
readonly STAGING_ROOT="/home/ubuntu/.autoflow-deploys"
readonly LOCK_FILE="/home/ubuntu/.autoflow-deploy.lock"
readonly ORIGINAL_COMMAND="${SSH_ORIGINAL_COMMAND:-}"

if [[ ! "$ORIGINAL_COMMAND" =~ ^deploy\ ([0-9a-f]{40})$ ]]; then
  echo "Comando de deploy inválido." >&2
  exit 64
fi

readonly DEPLOY_REVISION="${BASH_REMATCH[1]}"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Já existe outro deploy em andamento." >&2
  exit 75
fi

umask 077
mkdir -p "$STAGING_ROOT"
staging_dir="$(mktemp -d "$STAGING_ROOT/$DEPLOY_REVISION.XXXXXX")"

cleanup() {
  rm -rf -- "$staging_dir"
}
trap cleanup EXIT

tar \
  --extract \
  --gzip \
  --file - \
  --directory "$staging_dir" \
  --no-same-owner \
  --no-same-permissions

for required_file in Dockerfile docker-compose.yml docker-compose.vm.yml scripts/deploy-vm.sh; do
  if [[ ! -f "$staging_dir/$required_file" ]]; then
    echo "Pacote inválido: $required_file não foi encontrado." >&2
    exit 65
  fi
done

rsync -a --delete \
  --exclude '.env' \
  --exclude '.env.evolution' \
  --exclude 'instance/' \
  --exclude 'outputs/' \
  --exclude 'work/' \
  "$staging_dir/" "$APP_DIR/"

DEPLOY_REVISION="$DEPLOY_REVISION" \
bash "$APP_DIR/scripts/deploy-vm.sh"
