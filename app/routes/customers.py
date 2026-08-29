"""Compatibilidade de rotas para o controller de clientes."""

from app.controllers import customers_controller as _controller


globals().update(
    {
        name: getattr(_controller, name)
        for name in dir(_controller)
        if not name.startswith("__")
    }
)
__all__ = [name for name in dir(_controller) if not name.startswith("_")]
