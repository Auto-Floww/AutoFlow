"""Use case for searching approved knowledge documents."""

import app.services.knowledge_service as legacy


class SearchKnowledgeService:
    def execute(
        self,
        company_id: int,
        query_text: str,
        *,
        limit: int = 5,
        excerpt_size: int = 700,
    ) -> list[dict]:
        return legacy.KnowledgeService.search_knowledge(
            company_id,
            query_text,
            limit=limit,
            excerpt_size=excerpt_size,
        )


__all__ = ["SearchKnowledgeService"]
