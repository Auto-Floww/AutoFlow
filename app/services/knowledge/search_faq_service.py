"""Use case for searching approved FAQ entries."""

import app.services.knowledge_service as legacy


class SearchFaqService:
    def execute(
        self,
        company_id: int,
        query_text: str,
        *,
        limit: int = 5,
    ) -> list[dict]:
        return legacy.KnowledgeService.search_faq(
            company_id,
            query_text,
            limit=limit,
        )


__all__ = ["SearchFaqService"]
