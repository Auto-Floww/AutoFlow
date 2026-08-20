from app import create_app


flask_app = create_app()
celery = flask_app.extensions["celery"]

# Importa as tasks depois da inicializacao da app para registra-las no worker.
from app.tasks import ai_tasks  # noqa: E402,F401
