"""Indicadores operacionais do painel."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from flask import Blueprint, jsonify, render_template
from flask_login import current_user, login_required

from app.extensions import db
from app.models import (
    Appointment,
    Company,
    Conversation,
    Customer,
    Notification,
    Product,
    WhatsAppIntegration,
)
from app.models.base import utcnow
from app.routes.helpers import company_local, model_dict
from app.tenant import current_company_id


bp = Blueprint("dashboard", __name__)


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)


def _dashboard_data(company_id: int) -> dict:
    now = utcnow()
    company = db.session.get(Company, int(company_id))
    timezone_name = getattr(company, "timezone", "UTC") or "UTC"
    local_now = company_local(now, timezone_name)
    local_today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today = _utc_naive(local_today)
    week_start = _utc_naive(local_today - timedelta(days=local_today.weekday()))
    month_start = _utc_naive(local_today.replace(day=1))

    conversations_today = Conversation.for_company(company_id).filter(
        Conversation.created_at >= today
    ).count()
    conversations_week = Conversation.for_company(company_id).filter(
        Conversation.created_at >= week_start
    ).count()
    new_customers = Customer.for_company(company_id).filter(
        Customer.created_at >= month_start
    ).count()
    ai_resolved = Conversation.for_company(company_id).filter(
        Conversation.status == "RESOLVED",
        Conversation.assigned_user_id.is_(None),
    ).count()
    human_transfers = Conversation.for_company(company_id).filter(
        db.or_(
            Conversation.human_requested.is_(True),
            Conversation.assigned_user_id.is_not(None),
        )
    ).count()
    appointment_count = Appointment.for_company(company_id).filter(
        Appointment.starts_at >= today,
        Appointment.status.in_(("PENDING", "CONFIRMED")),
    ).count()
    opportunities = Customer.for_company(company_id).filter(
        Customer.crm_stage.in_(("QUALIFICADO", "PROPOSTA"))
    ).count()
    total_resolved = Conversation.for_company(company_id).filter(
        Conversation.status == "RESOLVED"
    ).count()
    active_now = Conversation.for_company(company_id).filter(
        Conversation.status.in_(("OPEN", "PENDING"))
    ).count()
    appointments_today = Appointment.for_company(company_id).filter(
        Appointment.starts_at >= today,
        Appointment.starts_at < today + timedelta(days=1),
        Appointment.status.in_(("PENDING", "CONFIRMED")),
    ).count()
    appointments_pending = Appointment.for_company(company_id).filter(
        Appointment.starts_at >= now, Appointment.status == "PENDING"
    ).count()

    chart_start = _utc_naive(local_today - timedelta(days=6))
    chart_conversations = (
        db.session.query(Conversation.created_at)
        .filter(
            Conversation.company_id == company_id,
            Conversation.created_at >= chart_start,
        )
        .all()
    )
    by_day = Counter(
        company_local(created_at, timezone_name).date().isoformat()
        for created_at, in chart_conversations
    )
    resolved_conversations = (
        db.session.query(Conversation.closed_at)
        .filter(
            Conversation.company_id == company_id,
            Conversation.status == "RESOLVED",
            Conversation.closed_at >= chart_start,
        )
        .all()
    )
    resolved_by_day = Counter(
        company_local(closed_at, timezone_name).date().isoformat()
        for closed_at, in resolved_conversations
        if closed_at is not None
    )
    chart_days = [local_today - timedelta(days=offset) for offset in range(6, -1, -1)]

    # As consultas de produto ficam na memoria estruturada da conversa. Isso evita
    # inventar um ranking quando ainda nao existem eventos suficientes.
    product_counter: Counter[str] = Counter()
    for memory, in (
        db.session.query(Conversation.memory_json)
        .filter(Conversation.company_id == company_id)
        .order_by(Conversation.last_message_at.desc())
        .limit(250)
    ):
        if not isinstance(memory, dict):
            continue
        for product in memory.get("products_consulted", []):
            label = product.get("name") if isinstance(product, dict) else product
            if label:
                product_counter[str(label)] += 1

    top_products = []
    for name, count in product_counter.most_common(5):
        product = Product.for_company(company_id).filter(Product.name == name).first()
        inventories = []
        if product:
            inventories = [variant.inventory for variant in product.variants if variant.inventory]
            if not inventories and product.inventory:
                inventories = [product.inventory]
        top_products.append(
            {
                "name": name,
                "queries": count,
                "consultations": count,
                "id": product.id if product else None,
                "sku": product.sku if product else None,
                "category": product.category if product else None,
                "image_url": product.image_url if product else None,
                "stock": sum(item.available_quantity for item in inventories),
                "minimum_stock": sum(item.minimum_quantity for item in inventories),
                "conversion": 0,
            }
        )

    upcoming = (
        Appointment.for_company(company_id)
        .filter(
            Appointment.starts_at >= now,
            Appointment.status.in_(("PENDING", "CONFIRMED")),
        )
        .order_by(Appointment.starts_at.asc())
        .limit(6)
        .all()
    )
    notifications = (
        Notification.for_company(company_id)
        .filter(
            Notification.is_read.is_(False),
            db.or_(Notification.user_id.is_(None), Notification.user_id == current_user.id),
        )
        .order_by(Notification.created_at.desc())
        .limit(8)
        .all()
    )

    metrics = {
            "conversations_today": conversations_today,
            "conversations_week": conversations_week,
            "new_customers": new_customers,
            "ai_resolved": ai_resolved,
            "human_transfers": human_transfers,
            "appointments": appointment_count,
            "opportunities": opportunities,
            "active_now": active_now,
            "total_resolved": total_resolved,
            "ai_resolution_rate": round(ai_resolved * 100 / total_resolved) if total_resolved else 0,
            "appointments_today": appointments_today,
            "appointments_pending": appointments_pending,
            "conversations_change": 0,
            "ai_change": 0,
            "customers_change": 0,
        }
    stage_counts = dict(
        db.session.query(Customer.crm_stage, db.func.count(Customer.id))
        .filter(Customer.company_id == company_id)
        .group_by(Customer.crm_stage)
        .all()
    )
    stage_keys = {
        "NOVO": "new",
        "INTERESSADO": "interested",
        "QUALIFICADO": "qualified",
        "PROPOSTA": "proposal",
        "VENDA": "sale",
        "PERDIDO": "lost",
    }
    pipeline = {stage_keys[key]: stage_counts.get(key, 0) for key in stage_keys}
    pipeline["total"] = sum(stage_counts.values())
    potential_value = (
        db.session.query(db.func.coalesce(db.func.sum(Customer.opportunity_value), 0))
        .filter(
            Customer.company_id == company_id,
            Customer.crm_stage.in_(("INTERESSADO", "QUALIFICADO", "PROPOSTA")),
        )
        .scalar()
        or Decimal("0")
    )
    pipeline["potential_value_label"] = "R$ " + f"{potential_value:,.2f}".replace(
        ",", "X"
    ).replace(".", ",").replace("X", ".")
    maximum = max(stage_counts.values(), default=0)
    for source, target in stage_keys.items():
        pipeline[f"{target}_percent"] = (
            round(stage_counts.get(source, 0) * 100 / maximum) if maximum else 0
        )
    chart_labels = [day.strftime("%d/%m") for day in chart_days]
    chart_values = [by_day.get(day.date().isoformat(), 0) for day in chart_days]
    resolved_values = [resolved_by_day.get(day.date().isoformat(), 0) for day in chart_days]
    whatsapp_connected = WhatsAppIntegration.for_company(company_id).filter_by(
        status="CONNECTED", is_active=True
    ).first() is not None
    notification_views = [
        {
            "id": item.id,
            "title": item.title,
            "description": item.body or "",
            "url": item.link_url or "#",
            "read": item.is_read,
            "time_ago": company_local(item.created_at, timezone_name).strftime(
                "%d/%m %H:%M"
            ),
            "icon": "bell",
        }
        for item in notifications
    ]
    return {
        "metrics": metrics,
        "stats": metrics,
        "pipeline_stats": pipeline,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "chart_data": {
            "labels": chart_labels,
            "started": chart_values,
            "resolved": resolved_values,
            "resolution": [ai_resolved, max(0, total_resolved - ai_resolved)],
        },
        "top_products": top_products,
        "upcoming_appointments": upcoming,
        "notifications": notifications,
        "nav_notifications": notification_views,
        "notification_count": len(notifications),
        "recent_activities": notification_views,
        "whatsapp_connected": whatsapp_connected,
    }


@bp.get("/dashboard")
@login_required
def index():
    data = _dashboard_data(current_company_id())
    return render_template("dashboard/index.html", **data)


@bp.get("/api/dashboard/metrics")
@login_required
def metrics():
    data = _dashboard_data(current_company_id())
    data["upcoming_appointments"] = [
        model_dict(item, "id", "starts_at", "ends_at", "status")
        for item in data["upcoming_appointments"]
    ]
    data["notifications"] = [
        model_dict(item, "id", "notification_type", "title", "body", "link_url", "created_at")
        for item in data["notifications"]
    ]
    return jsonify(data)


@bp.post("/api/notifications/<int:notification_id>/read")
@login_required
def read_notification(notification_id: int):
    notification = Notification.get_for_company(current_company_id(), notification_id)
    if notification is None or notification.user_id not in {None, current_user.id}:
        return jsonify(error="not_found"), 404
    notification.is_read = True
    notification.read_at = utcnow()
    db.session.commit()
    return jsonify(ok=True)
