"""Compatibilidade para ferramentas que importam a configuração pela raiz."""

from app.config import CONFIGS, Config, DevelopmentConfig, ProductionConfig, TestingConfig


__all__ = [
    "CONFIGS",
    "Config",
    "DevelopmentConfig",
    "ProductionConfig",
    "TestingConfig",
]
