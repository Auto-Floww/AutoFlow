"""Authentication Blueprint wiring and compatibility handler exports."""

from app.controllers.auth_controller import AuthController, bp

register = AuthController.register
login = AuthController.login
logout = AuthController.logout
forgot_password = AuthController.forgot_password
reset_password = AuthController.reset_password
change_password = AuthController.change_password

__all__ = [
    "AuthController",
    "bp",
    "change_password",
    "forgot_password",
    "login",
    "logout",
    "register",
    "reset_password",
]
