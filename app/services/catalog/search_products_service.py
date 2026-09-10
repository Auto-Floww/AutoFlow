"""Caso de uso para pesquisar no catálogo de produtos de um determinado tenant (cliente ou organização)."""

import app.services.catalog_service as legacy


class SearchProductsService:
    def execute(
        self,
        company_id: int,
        *,
        query_text: str | None = None,
        category: str | None = None,
        active_only: bool = True,
        limit: int = 20,
    ):
        return legacy.CatalogService.search(
            company_id,
            query_text=query_text,
            category=category,
            active_only=active_only,
            limit=limit,
        )


__all__ = ["SearchProductsService"]
