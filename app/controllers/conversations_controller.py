"""Central de conversas e handoff entre IA e equipe humana."""

from __future__ import annotations

from flask import Blueprint, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from app.extensions import db, limiter
from app.models import AISettings, Conversation, ConversationTag, Customer, Message, Tag
from app.models.base import utcnow
from app.controllers.http import company_local, failure, model_dict, payload, record_audit, success, wants_json
from app.services.conversations import (
    AddConversationTagService,
    ClaimConversationService,
    GetOrCreateConversationService,
    RecordOutboundMessageService,
    ReturnConversationToAiService,
)
from app.services.customers import CreateCustomerService, FindCustomerByPhoneService
from app.services.exceptions import DomainError
from app.services.outbox import (
    DispatchOutboxBestEffortService,
    EnqueueOutboxTaskService,
)
from app.tenant import current_company_id, tenant_get_or_404


bp = Blueprint("conversations", __name__, url_prefix="/conversations")


def _serialize_message(message: Message) -> dict:
    data = model_dict(
        message,
        "id",
        "conversation_id",
        "direction",
        "sender_type",
        "message_type",
        "content",
        "status",
        "created_at",
        "sent_at",
        "delivered_at",
        "read_at",
    )
    data["sender_name"] = getattr(message.sender_user, "name", None)
    return data


def _serialize_conversation(conversation: Conversation) -> dict:
    last_message = conversation.messages.order_by(Message.created_at.desc()).first()
    return {
        **model_dict(
            conversation,
            "id",
            "status",
            "ai_status",
            "human_requested",
            "unread_count",
            "last_message_at",
            "assigned_user_id",
        ),
        "customer": {
            "id": conversation.customer.id,
            "name": conversation.customer.name,
            "phone": conversation.customer.phone,
            "email": conversation.customer.email,
            "crm_stage": conversation.customer.crm_stage,
        },
        "last_message": last_message.content if last_message else "",
        "tags": [
            {"id": link.tag.id, "name": link.tag.name, "color": link.tag.color}
            for link in conversation.tag_links
            if link.tag and link.tag.is_active
        ],
    }


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    timezone_name = getattr(current_user.company, "timezone", "UTC") or "UTC"
    query = Conversation.for_company(company_id).join(Conversation.customer)
    search = request.args.get("q", "").strip()
    status = request.args.get("status", "").upper()
    ai_status = request.args.get("ai_status", "").upper()
    if search:
        pattern = f"%{search}%"
        query = query.filter(
            or_(
                Customer.name.ilike(pattern),
                Customer.phone.ilike(pattern),
                Customer.email.ilike(pattern),
            )
        )
    if status in {"OPEN", "PENDING", "RESOLVED", "CLOSED"}:
        query = query.filter(Conversation.status == status)
    if ai_status in {"ACTIVE", "PAUSED", "DISABLED"}:
        query = query.filter(Conversation.ai_status == ai_status)
    customer_id = request.args.get("customer_id", type=int)
    if customer_id:
        query = query.filter(Conversation.customer_id == customer_id)
    conversations = query.order_by(
        Conversation.last_message_at.desc(), Conversation.updated_at.desc()
    ).limit(100).all()
    unread_conversations = 0
    for item in conversations:
        last_message = item.messages.order_by(Message.created_at.desc()).first()
        item.last_message = last_message.content if last_message else ""
        item.last_message_text = item.last_message
        item.last_message_from_agent = bool(last_message and last_message.direction == "OUTBOUND")
        item.tags = [link.tag for link in item.tag_links if link.tag and link.tag.is_active]
        local_last_message = company_local(item.last_message_at, timezone_name)
        local_updated = company_local(item.updated_at, timezone_name)
        item.time_label = local_last_message.strftime("%H:%M") if local_last_message else ""
        item.updated_label = local_updated.strftime("%d/%m %H:%M") if local_updated else ""
        if item.unread_count:
            unread_conversations += 1

    selected = None
    selected_id = request.args.get("conversation", type=int)
    if selected_id:
        selected = Conversation.get_for_company(company_id, selected_id)
    if selected is None and conversations:
        selected = conversations[0]
    messages = (
        selected.messages.order_by(Message.created_at.asc()).limit(200).all()
        if selected
        else []
    )
    for message in messages:
        local_created = company_local(message.created_at, timezone_name)
        message.time_label = local_created.strftime("%H:%M") if local_created else ""
        message.date_label = local_created.strftime("%d/%m/%Y") if local_created else ""
        message.sender_name = getattr(message.sender_user, "name", None)
    if selected:
        selected.customer.tags = [
            link.tag for link in selected.customer.tag_links if link.tag and link.tag.is_active
        ]
        selected.customer.location = (selected.customer.preferences_json or {}).get("location")
    if selected and selected.unread_count:
        selected.unread_count = 0
        db.session.commit()

    tags = Tag.for_company(company_id).filter(Tag.is_active.is_(True)).order_by(Tag.name).all()
    ai_settings = AISettings.for_company(company_id).one_or_none()
    return render_template(
        "conversations/index.html",
        conversations=conversations,
        active_conversation=selected,
        conversation=selected,
        messages=messages,
        tags=tags,
        unread_conversations=unread_conversations,
        total_conversations=len(conversations),
        poll_url=(url_for("conversations.detail", conversation_id=selected.id) if selected else ""),
        ai_name=(ai_settings.assistant_name if ai_settings else "Assistente IA"),
        filters={"q": search, "status": status, "ai_status": ai_status},
    )


@bp.get("/<int:conversation_id>")
@login_required
def detail(conversation_id: int):
    if not wants_json():
        return redirect(url_for("conversations.index", conversation=conversation_id))
    conversation = tenant_get_or_404(Conversation, conversation_id)
    after_id = request.args.get("after", 0, type=int)
    query = conversation.messages.order_by(Message.created_at.asc())
    if after_id:
        query = query.filter(Message.id > after_id)
    messages = query.limit(250).all()
    conversation.unread_count = 0
    db.session.commit()
    return jsonify(
        conversation=_serialize_conversation(conversation),
        messages=[_serialize_message(message) for message in messages],
    )


@bp.post("")
@login_required
@limiter.limit("20 per minute")
def create():
    data = payload()
    phone = str(data.get("phone", "")).strip()
    body = str(data.get("message", data.get("body", ""))).strip()
    if not phone or not body:
        return failure("Informe telefone e mensagem.", status=422)
    company_id = current_company_id()
    try:
        customer = FindCustomerByPhoneService().execute(company_id, phone)
        if customer is None:
            customer = CreateCustomerService().execute(
                company_id, name=str(data.get("name", phone)), phone=phone, source="MANUAL"
            )
        conversation, _ = GetOrCreateConversationService().execute(
            company_id, customer_id=customer.id, channel="WHATSAPP"
        )
        ClaimConversationService().execute(
            company_id, conversation.id, user_id=current_user.id
        )
        message = RecordOutboundMessageService().execute(
            company_id,
            conversation_id=conversation.id,
            content=body,
            sender_type="AGENT",
            sender_user_id=current_user.id,
            commit=False,
        )
        outbox = EnqueueOutboxTaskService().execute(
            "send_whatsapp_message",
            {"message_id": message.id},
            idempotency_key=f"send-whatsapp-message:{message.id}",
            company_id=company_id,
        )
        db.session.commit()
    except DomainError as exc:
        db.session.rollback()
        return failure(exc.message, status=exc.status_code)
    DispatchOutboxBestEffortService().execute(outbox.id)
    return success(
        "Conversa iniciada.",
        data={"conversation_id": conversation.id},
        endpoint="conversations.index",
        status=201,
    )


@bp.post("/<int:conversation_id>/assume")
@login_required
@limiter.limit("60 per minute")
def assume(conversation_id: int):
    try:
        conversation = ClaimConversationService().execute(
            current_company_id(), conversation_id, user_id=current_user.id
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    record_audit("conversation.assume", conversation, {"ai_status": "PAUSED"})
    db.session.commit()
    return success("Atendimento assumido. A IA foi pausada.", data=_serialize_conversation(conversation))


@bp.post("/<int:conversation_id>/return-to-ai")
@bp.post("/<int:conversation_id>/return_to_ai")
@login_required
@limiter.limit("60 per minute")
def return_to_ai(conversation_id: int):
    try:
        conversation = ReturnConversationToAiService().execute(
            current_company_id(), conversation_id, user_id=current_user.id
        )
    except DomainError as exc:
        return failure(exc.message, status=exc.status_code)
    record_audit("conversation.return_to_ai", conversation, {"ai_status": "ACTIVE"})
    db.session.commit()
    return success("Conversa devolvida para a IA.", data=_serialize_conversation(conversation))


@bp.post("/<int:conversation_id>/resolve")
@login_required
def resolve(conversation_id: int):
    conversation = tenant_get_or_404(Conversation, conversation_id)
    conversation.status = "RESOLVED"
    conversation.closed_at = utcnow()
    record_audit("conversation.resolve", conversation, {"status": "RESOLVED"})
    db.session.commit()
    return success("Conversa marcada como resolvida.", data=_serialize_conversation(conversation))


@bp.post("/<int:conversation_id>/messages")
@bp.post("/<int:conversation_id>/send")
@login_required
@limiter.limit("60 per minute")
def send_message(conversation_id: int):
    conversation = tenant_get_or_404(Conversation, conversation_id)
    body = str(payload().get("body", payload().get("message", ""))).strip()
    if not body or len(body) > 4096:
        return failure("Digite uma mensagem de ate 4096 caracteres.")
    auto_claimed = False
    try:
        # Sending from the human composer is itself an explicit handoff action.
        # Claim atomically here so an operator does not hit a confusing 409 when
        # the page still shows the conversation as AI-controlled.
        if conversation.ai_status == "ACTIVE":
            conversation = ClaimConversationService().execute(
                current_company_id(),
                conversation.id,
                user_id=current_user.id,
                commit=False,
            )
            auto_claimed = True
        message = RecordOutboundMessageService().execute(
            current_company_id(),
            conversation_id=conversation.id,
            content=body,
            sender_type="AGENT",
            sender_user_id=current_user.id,
            commit=False,
        )
        outbox = EnqueueOutboxTaskService().execute(
            "send_whatsapp_message",
            {"message_id": message.id},
            idempotency_key=f"send-whatsapp-message:{message.id}",
            company_id=current_company_id(),
        )
        db.session.commit()
    except DomainError as exc:
        db.session.rollback()
        return failure(exc.message, status=exc.status_code)
    DispatchOutboxBestEffortService().execute(outbox.id)
    return success(
        "Mensagem adicionada a fila.",
        data={
            "message": _serialize_message(message),
            "conversation": _serialize_conversation(conversation),
            "auto_claimed": auto_claimed,
        },
        status=201,
    )


@bp.post("/<int:conversation_id>/tags")
@login_required
def add_tag(conversation_id: int):
    company_id = current_company_id()
    conversation = tenant_get_or_404(Conversation, conversation_id)
    tag_id = int(payload().get("tag_id", 0) or 0)
    tag = Tag.get_for_company(company_id, tag_id)
    if tag is None:
        return failure("Tag nao encontrada.", status=404)
    exists = ConversationTag.for_company(company_id).filter_by(
        conversation_id=conversation.id, tag_id=tag.id
    ).first()
    AddConversationTagService().execute(
        company_id,
        conversation.id,
        tag.id,
        commit=False,
    )
    if not exists:
        db.session.commit()
    return success("Tag adicionada.")


@bp.delete("/<int:conversation_id>/tags/<int:tag_id>")
@login_required
def remove_tag(conversation_id: int, tag_id: int):
    company_id = current_company_id()
    tenant_get_or_404(Conversation, conversation_id)
    link = ConversationTag.for_company(company_id).filter_by(
        conversation_id=conversation_id, tag_id=tag_id
    ).first_or_404()
    db.session.delete(link)
    db.session.commit()
    return success("Tag removida.")


class ConversationsController:
    """Controlador HTTP para operações de conversas e transferência para atendimento humano."""

    index = staticmethod(index)
    detail = staticmethod(detail)
    create = staticmethod(create)
    assume = staticmethod(assume)
    return_to_ai = staticmethod(return_to_ai)
    resolve = staticmethod(resolve)
    send_message = staticmethod(send_message)
    add_tag = staticmethod(add_tag)
    remove_tag = staticmethod(remove_tag)


bp.view_functions.update(
    {
        "index": ConversationsController.index,
        "detail": ConversationsController.detail,
        "create": ConversationsController.create,
        "assume": ConversationsController.assume,
        "return_to_ai": ConversationsController.return_to_ai,
        "resolve": ConversationsController.resolve,
        "send_message": ConversationsController.send_message,
        "add_tag": ConversationsController.add_tag,
        "remove_tag": ConversationsController.remove_tag,
    }
)
