#!/usr/bin/env bash
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/autoflow}"
PROJECT_NAME="${PROJECT_NAME:-autoflow}"
DEPLOY_REVISION="${DEPLOY_REVISION:-manual}"

cd "$APP_DIR"

if [[ ! -s .env ]]; then
  echo "Erro: $APP_DIR/.env não existe ou está vazio." >&2
  exit 1
fi

compose=(
  docker compose
  --project-name "$PROJECT_NAME"
  --env-file "$APP_DIR/.env"
  -f "$APP_DIR/docker-compose.yml"
  -f "$APP_DIR/docker-compose.vm.yml"
)

"${compose[@]}" config --quiet

rollback_available=false
if docker image inspect autoflow-web:latest >/dev/null 2>&1; then
  docker tag autoflow-web:latest autoflow-web:rollback
  rollback_available=true
fi

restore_previous_release() {
  if [[ "$rollback_available" != "true" ]]; then
    echo "Não existe uma imagem anterior para restauração automática." >&2
    return
  fi

  docker tag autoflow-web:rollback autoflow-web:latest
  docker tag autoflow-web:rollback autoflow-worker:latest
  docker tag autoflow-web:rollback autoflow-beat:latest
  "${compose[@]}" up -d --no-build web worker beat
}

echo "Construindo a revisão $DEPLOY_REVISION..."
docker build \
  --label "io.autoflow.revision=$DEPLOY_REVISION" \
  -t autoflow-web:latest \
  "$APP_DIR"
docker tag autoflow-web:latest autoflow-worker:latest
docker tag autoflow-web:latest autoflow-beat:latest

if ! "${compose[@]}" up -d --no-build --remove-orphans; then
  echo "A atualização dos serviços falhou. Restaurando a imagem anterior..." >&2
  restore_previous_release
  exit 1
fi

web_container="$("${compose[@]}" ps -q web)"
if [[ -z "$web_container" ]]; then
  echo "Erro: o container web não foi criado." >&2
  restore_previous_release
  exit 1
fi

healthy=false
for _ in {1..18}; do
  health_status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$web_container")"
  if [[ "$health_status" == "healthy" ]]; then
    healthy=true
    break
  fi
  if [[ "$health_status" == "unhealthy" || "$health_status" == "exited" || "$health_status" == "dead" ]]; then
    break
  fi
  sleep 10
done

if [[ "$healthy" != "true" ]]; then
  echo "A nova versão não ficou saudável. Restaurando a imagem anterior..." >&2
  "${compose[@]}" logs --tail 100 web >&2 || true

  restore_previous_release

  exit 1
fi

docker image rm autoflow-web:rollback >/dev/null 2>&1 || true
docker image prune -f

echo "Revisão $DEPLOY_REVISION publicada com sucesso."
"${compose[@]}" ps
