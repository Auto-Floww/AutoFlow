"""Extensoes Flask compartilhadas pela aplicacao.

Os objetos ficam neste modulo para evitar ciclos de importacao entre a factory,
os blueprints e os modelos.
"""

from celery import Celery
from flask_cors import CORS
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import MetaData


NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))
migrate = Migrate(compare_type=True, render_as_batch=False)
login_manager = LoginManager()
csrf = CSRFProtect()
cors = CORS()
limiter = Limiter(key_func=get_remote_address, default_limits=[])


def make_celery(app=None) -> Celery:
    """Cria uma instancia Celery que executa tasks no contexto do Flask."""

    broker = app.config["CELERY_BROKER_URL"] if app else "redis://localhost:6379/0"
    backend = app.config["CELERY_RESULT_BACKEND"] if app else broker
    celery = Celery("autoflow", broker=broker, backend=backend)
    if app is not None:
        celery.conf.update(app.config.get("CELERY", {}))

        class FlaskTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with app.app_context():
                    return self.run(*args, **kwargs)

        celery.Task = FlaskTask
        app.extensions["celery"] = celery
    return celery
