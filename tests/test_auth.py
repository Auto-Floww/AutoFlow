"""Autenticação, sessão e recuperação de senha."""

from app.extensions import db
from app.models import Company, CompanyMember, TaskOutbox, User
from app.security import decrypt_secret
from app.services.email_service import EmailService
from app.tasks.ai_tasks import password_reset_email


def test_register_creates_owner_company_and_password_hash(client, app):
    response = client.post(
        "/register",
        json={
            "name": "Gabriel Silva",
            "email": "GABRIEL@example.com",
            "password": "SenhaSegura123!",
            "company_name": "Loja Aurora",
        },
    )

    assert response.status_code == 201
    assert response.get_json()["ok"] is True
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "gabriel@example.com"))
        assert user is not None
        assert user.password_hash != "SenhaSegura123!"
        assert user.check_password("SenhaSegura123!")
        assert user.active_company.name == "Loja Aurora"
        membership = db.session.scalar(
            db.select(CompanyMember).where(CompanyMember.user_id == user.id)
        )
        assert membership.role == "OWNER"
        assert db.session.scalar(db.select(db.func.count(Company.id))) == 1


def test_login_rejects_wrong_password_and_accepts_normalized_email(
    client, tenant_user
):
    rejected = client.post(
        "/login", json={"email": tenant_user.email, "password": "incorreta"}
    )
    assert rejected.status_code == 401
    assert rejected.get_json()["ok"] is False

    accepted = client.post(
        "/login",
        json={"email": tenant_user.email.upper(), "password": "SenhaSegura123!"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["redirect"] == "/dashboard"


def test_protected_page_redirects_anonymous_user(client):
    response = client.get("/dashboard")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_logout_clears_session(client, tenant_user):
    assert client.post(
        "/login",
        json={"email": tenant_user.email, "password": "SenhaSegura123!"},
    ).status_code == 200

    response = client.post("/logout", json={})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert client.get("/dashboard").status_code == 302


def test_forgot_and_reset_password_never_reveals_account_existence(
    client, app, tenant_user, monkeypatch, caplog
):
    app.config["APP_URL"] = "https://painel.autoflow.example"
    missing = client.post(
        "/forgot-password",
        json={"email": "missing@example.com"},
        headers={"Host": "host-nao-confiavel.example"},
    )
    found = client.post(
        "/forgot-password",
        json={"email": tenant_user.email},
        headers={"Host": "host-nao-confiavel.example"},
    )

    assert missing.status_code == found.status_code == 200
    assert missing.get_json()["message"] == found.get_json()["message"]
    assert missing.get_json()["data"] == found.get_json()["data"] == {
        "delivery": "email"
    }

    outboxes = TaskOutbox.query.order_by(TaskOutbox.id).all()
    assert len(outboxes) == 2
    assert outboxes[0].task_name == "password_reset_email"
    assert outboxes[0].payload_json == {}
    known_outbox = outboxes[1]
    assert known_outbox.status == "PENDING"
    assert known_outbox.payload_json["user_id"] == tenant_user.id
    token = decrypt_secret(known_outbox.payload_json["reset_token_encrypted"])
    assert token
    assert token not in known_outbox.payload_json["reset_token_encrypted"]

    delivered = []

    def fake_send_password_reset(recipient, reset_url):
        delivered.append((recipient, reset_url))
        return {"status": "sent"}

    monkeypatch.setattr(
        EmailService,
        "send_password_reset",
        staticmethod(fake_send_password_reset),
    )
    assert password_reset_email.run(**known_outbox.payload_json) == {
        "status": "sent",
        "user_id": tenant_user.id,
    }
    assert delivered == [
        (
            tenant_user.email,
            f"https://painel.autoflow.example/reset-password/{token}",
        )
    ]
    assert "host-nao-confiavel.example" not in delivered[0][1]
    assert token not in caplog.text

    changed = client.post(
        f"/reset-password/{token}",
        json={"password": "SenhaNova456!", "confirm_password": "SenhaNova456!"},
    )
    assert changed.status_code == 200
    assert client.post(
        f"/reset-password/{token}",
        json={"password": "OutraSenha789!", "confirm_password": "OutraSenha789!"},
    ).status_code == 400
    with app.app_context():
        user = db.session.get(User, tenant_user.id)
        assert user.check_password("SenhaNova456!")
