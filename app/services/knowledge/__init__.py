"""Casos de uso para pesquisa em perguntas frequentes (FAQ) e na base de conhecimento."""

from app.services.knowledge.search_faq_service import SearchFaqService
from app.services.knowledge.search_knowledge_service import SearchKnowledgeService

__all__ = ["SearchFaqService", "SearchKnowledgeService"]
