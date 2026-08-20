"""Ambiente Alembic integrado ao contexto da aplicação Flask."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from flask import current_app


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_engine():
    """Obtém o engine mantido pela extensão Flask-SQLAlchemy."""

    return current_app.extensions["migrate"].db.engine


def get_engine_url() -> str:
    """Retorna uma URL segura para interpolacão no arquivo Alembic."""

    return str(get_engine().url).replace("%", "%%")


config.set_main_option("sqlalchemy.url", get_engine_url())
target_metadata = current_app.extensions["migrate"].db.metadata


def run_migrations_offline() -> None:
    """Executa migrações sem abrir uma conexão com o banco."""

    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Executa migrações usando a conexão configurada pela aplicação."""

    configure_args = current_app.extensions["migrate"].configure_args
    if configure_args.get("process_revision_directives") is None:

        def process_revision_directives(migration_context, revision, directives):
            if getattr(config.cmd_opts, "autogenerate", False):
                script = directives[0]
                if script.upgrade_ops.is_empty():
                    directives[:] = []

        configure_args["process_revision_directives"] = process_revision_directives

    with get_engine().connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            **configure_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
