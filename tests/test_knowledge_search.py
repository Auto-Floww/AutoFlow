from app.extensions import db
from app.models import KnowledgeDocument
from app.services.knowledge_service import KnowledgeSearch


def test_search_returns_excerpt_near_the_content_match(company_factory):
    company = company_factory()
    other = company_factory()
    text = "Introdução sem relação com a pergunta. " * 30
    policy = "Política de troca: até 30 dias após a compra."
    doc = KnowledgeDocument(
        company_id=company.id, title="Manual", content=f"{text}\n{policy}"
    )
    db.session.add_all(
        [
            doc,
            KnowledgeDocument(company_id=other.id, title="Manual", content=policy),
            KnowledgeDocument(
                company_id=company.id, title="Rascunho", content=policy, status="PROCESSING"
            ),
        ]
    )
    db.session.flush()

    results = KnowledgeSearch.search_knowledge(
        company.id, "política de troca", excerpt_size=100
    )

    assert [item["id"] for item in results] == [doc.id]
    assert policy in results[0]["excerpt"]
    assert len(results[0]["excerpt"]) == 100


def test_search_uses_beginning_when_only_the_title_matches(company_factory):
    company = company_factory()
    doc = KnowledgeDocument(company_id=company.id, title="Trocas", content="Prazo de 30 dias.")
    db.session.add(doc)
    db.session.flush()

    results = KnowledgeSearch.search_knowledge(company.id, "Trocas")

    assert results[0]["excerpt"] == "Prazo de 30 dias."
