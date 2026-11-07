"""Pesquisa limitada de perguntas frequentes (FAQ) e da base de conhecimento de um determinado tenant (empresa ou organização)."""

from __future__ import annotations

import re

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
                            KnowledgeDocument.title.icontains(term, autoescape=True),
                            KnowledgeDocument.content.icontains(term, autoescape=True),
                        )
                        for term in terms
                    ]
                )
            )
        rows = query.order_by(KnowledgeDocument.updated_at.desc()).limit(min(limit, 10)).all()
        excerpt_size = max(100, min(excerpt_size, 1500))
        candidates = [text, *sorted(terms, key=len, reverse=True)]
        return [
            {
                "id": row.id,
                "title": row.title,
                "excerpt": KnowledgeSearch._excerpt(row.content, candidates, excerpt_size),
                "source_url": row.source_url,
            }
            for row in rows
        ]

    @staticmethod
    def _excerpt(content: str, candidates: list[str], size: int) -> str:
        for candidate in candidates:
            match = re.search(re.escape(candidate), content, re.IGNORECASE)
            if match:
                context_before = min(size // 4, max(0, size - len(candidate)))
                start = max(0, match.start() - context_before)
                start = min(start, max(0, len(content) - size))
                return content[start : start + size]
        return content[:size]


# Backwards-compatible alias; use-case Services live in ``app.services.knowledge``.
KnowledgeService = KnowledgeSearch
