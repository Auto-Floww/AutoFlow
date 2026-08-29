"""Compatibilidade de rotas para o controller de estoque."""

from app.controllers import inventory_controller as _controller


globals().update(
    {
        name: getattr(_controller, name)
        for name in dir(_controller)
        if not name.startswith("__")
    }
)
__all__ = [name for name in dir(_controller) if not name.startswith("_")]
