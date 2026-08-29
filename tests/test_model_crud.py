"""Contrato CRUD compartilhado por todas as Models SQLAlchemy."""

from __future__ import annotations

import pytest

from app import models as model_package  # noqa: F401 - registers every mapper
from app.extensions import db
from app.models import Company
from app.models.base import CrudMixin


CRUD_METHODS = (
    "criar",
    "create",
    "salvar",
    "save",
    "buscar_por_id",
    "get_by_id",
    "listar_todos",
    "get_all",
    "atualizar",
    "update",
    "deletar",
    "delete",
)

MODEL_CLASSES = tuple(
    sorted(
        {mapper.class_ for mapper in db.Model.registry.mappers},
        key=lambda model_class: model_class.__name__,
    )
)


@pytest.mark.parametrize(
    "model_class",
    MODEL_CLASSES,
    ids=lambda model_class: model_class.__name__,
)
def test_every_model_exposes_the_complete_crud_contract(model_class):
    assert issubclass(model_class, CrudMixin)
    assert all(callable(getattr(model_class, method)) for method in CRUD_METHODS)


def test_crud_aliases_persist_update_delete_and_support_flush_without_commit(app):
    pending = Company.create(
        name="Empresa pendente",
        slug="empresa-pendente-crud",
        commit=False,
    )
    pending_id = pending.id

    assert pending_id is not None
    assert Company.get_by_id(pending_id) is pending

    db.session.rollback()

    assert Company.buscar_por_id(pending_id) is None

    company = Company(
        name="Empresa CRUD",
        slug="empresa-crud",
    ).save()

    assert Company.buscar_por_id(company.id) is company
    assert company in Company.get_all()
    assert company in Company.listar_todos()

    company.update(name="Empresa atualizada")
    assert Company.get_by_id(company.id).name == "Empresa atualizada"

    with pytest.raises(AttributeError, match="Campo protegido: company_id"):
        company.atualizar(name="Mutação parcial", company_id=123)
    assert company.name == "Empresa atualizada"

    with pytest.raises(AttributeError, match="Campo desconhecido"):
        company.update(campo_inexistente="valor")

    company_id = company.id
    company.delete()

    assert Company.get_by_id(company_id) is None
