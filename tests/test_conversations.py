"""Central de conversas e handoff IA/humano."""

from app.extensions import db
from app.models import Conversation, Customer, Message, TaskOutbox


def _conversation(company_id: int) -> Conversation:
    customer = Customer(
        company_id=company_id,
        name="Cliente WhatsApp",
        phone="+5511999992222",
        phone_normalized="5511999992222",
    )
    db.session.add(customer)
    db.session.flush()
    conversation = Conversation(
        company_id=company_id,
        customer_id=customer.id,
        external_id="wa-conversation-1",
        ai_status="ACTIVE",
        unread_count=1,
    )
    db.session.add(conversation)
    db.session.commit()
    return conversation


def test_assume_pauses_ai_and_return_reactivates_it(
    client, login_as, tenant_user
):
    conversation = _conversation(tenant_user.company_id)
    login_as(tenant_user)

    assumed = client.post(f"/conversations/{conversation.id}/assume", json={})
    assert assumed.status_code == 200
    assert assumed.get_json()["data"]["ai_status"] == "PAUSED"
    db.session.refresh(conversation)
    assert conversation.assigned_user_id == tenant_user.id

    returned = client.post(
        f"/conversations/{conversation.id}/return-to-ai", json={}
    )
    assert returned.status_code == 200
    db.session.refresh(conversation)
    assert conversation.ai_status == "ACTIVE"
    assert conversation.assigned_user_id is None


def test_agent_message_is_persisted_before_async_send(
    client, login_as, tenant_user
):
    conversation = _conversation(tenant_user.company_id)
    conversation.ai_status = "PAUSED"
    conversation.assigned_user_id = tenant_user.id
    db.session.commit()
    login_as(tenant_user)
    response = client.post(
        f"/conversations/{conversation.id}/messages",
        json={"body": "Olá, vou continuar seu atendimento."},
    )

    assert response.status_code == 201
    message = Message.query.filter_by(conversation_id=conversation.id).one()
    assert message.content == "Olá, vou continuar seu atendimento."
    assert message.sender_type == "AGENT"
    assert message.status == "QUEUED"
    outbox = TaskOutbox.query.one()
    assert outbox.company_id == tenant_user.company_id
    assert outbox.task_name == "send_whatsapp_message"
    assert outbox.idempotency_key == f"send-whatsapp-message:{message.id}"
    assert outbox.payload_json == {"message_id": message.id}
    assert outbox.status == "PENDING"


def test_human_send_auto_claims_conversation_while_ai_is_active(
    client, login_as, tenant_user
):
    conversation = _conversation(tenant_user.company_id)
    login_as(tenant_user)

    response = client.post(
        f"/conversations/{conversation.id}/messages", json={"body": "Mensagem"}
    )

    assert response.status_code == 201
    assert response.get_json()["data"]["auto_claimed"] is True
    db.session.refresh(conversation)
    assert conversation.ai_status == "PAUSED"
    assert conversation.assigned_user_id == tenant_user.id
    assert Message.query.filter_by(conversation_id=conversation.id).count() == 1
