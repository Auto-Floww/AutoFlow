"""Compatibilidade de rotas para o controller de FAQ."""

from app.controllers import faq_controller as _controller


globals().update(
    {
        name: getattr(_controller, name)
        for name in dir(_controller)
        if not name.startswith("__")
    }
)
__all__ = [name for name in dir(_controller) if not name.startswith("_")]
