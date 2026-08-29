"""Bounded tenant-scoped FAQ and knowledge search."""

from __future__ import annotations

from app.extensions import db
from app.models import FAQ, KnowledgeDocument


class KnowledgeSearch:
    @staticmethod
    def search_faq(company_id: int, query_text: str, *, limit: int = 5) -> list[dict]:
        text = (query_text or "").strip()[:200]
        if not text:
            return []
        terms = [term for term in text.split() if len(term) > 1][:8]
        query = FAQ.for_company(company_id).filter(FAQ.is_active.is_(True))
        if terms:
            query = query.filter(
                db.or_(
                    *[
                        db.or_(
                            FAQ.question.ilike(f"%{term}%"),
                            FAQ.answer.ilike(f"%{term}%"),
                            FAQ.category.ilike(f"%{term}%"),
                        )
                        for term in terms
                    ]
                )
            )
        rows = query.order_by(FAQ.priority, FAQ.updated_at.desc()).limit(min(limit, 10)).all()
        return [
            {"id": row.id, "question": row.question, "answer": row.answer, "category": row.category}
            for row in rows
        ]

    @staticmethod
    def search_knowledge(
        company_id: int, query_text: str, *, limit: int = 5, excerpt_size: int = 700
    ) -> list[dict]:
        text = (query_text or "").strip()[:200]
        if not text:
            return []
        terms = [term for term in text.split() if len(term) > 1][:8]
        query = KnowledgeDocument.for_company(company_id).filter(
            KnowledgeDocument.is_active.is_(True), KnowledgeDocument.status == "READY"
        )
        if terms:
            query = query.filter(
                db.or_(
                    *[
                        db.or_(
                            KnowledgeDocument.title.ilike(f"%{term}%"),
                            KnowledgeDocument.content.ilike(f"%{term}%"),
                        )
                        for term in terms
                    ]
                )
            )
        rows = query.order_by(KnowledgeDocument.updated_at.desc()).limit(min(limit, 10)).all()
        return [
            {
                "id": row.id,
                "title": row.title,
                "excerpt": row.content[: max(100, min(excerpt_size, 1500))],
                "source_url": row.source_url,
            }
            for row in rows
        ]


# Backwards-compatible alias; use-case Services live in ``app.services.knowledge``.
KnowledgeService = KnowledgeSearch
