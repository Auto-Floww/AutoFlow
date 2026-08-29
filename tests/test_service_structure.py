"""Structural contract for use-case services grouped by domain."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


SERVICE_ROOT = Path(__file__).resolve().parents[1] / "app" / "services"

EXPECTED_CASES = {
    "ai/answer_conversation_service.py": "AnswerConversationService",
    "ai/summarize_conversation_service.py": "SummarizeConversationService",
    "appointments/cancel_appointment_service.py": "CancelAppointmentService",
    "appointments/create_appointment_service.py": "CreateAppointmentService",
    "appointments/get_appointment_service.py": "GetAppointmentService",
    "appointments/get_available_appointments_service.py": "GetAvailableAppointmentsService",
    "auth/send_password_reset_email_service.py": "SendPasswordResetEmailService",
    "catalog/get_product_service.py": "GetProductService",
    "catalog/search_products_service.py": "SearchProductsService",
    "conversations/add_conversation_tag_service.py": "AddConversationTagService",
    "conversations/build_groq_conversation_history_range_service.py": (
        "BuildGroqConversationHistoryRangeService"
    ),
    "conversations/build_groq_conversation_history_service.py": (
        "BuildGroqConversationHistoryService"
    ),
    "conversations/claim_conversation_service.py": "ClaimConversationService",
    "conversations/get_conversation_service.py": "GetConversationService",
    "conversations/get_or_create_conversation_service.py": "GetOrCreateConversationService",
    "conversations/list_recent_messages_service.py": "ListRecentMessagesService",
    "conversations/mark_conversation_read_service.py": "MarkConversationReadService",
    "conversations/record_inbound_message_service.py": "RecordInboundMessageService",
    "conversations/record_outbound_message_service.py": "RecordOutboundMessageService",
    "conversations/return_conversation_to_ai_service.py": "ReturnConversationToAiService",
    "conversations/set_conversation_summary_service.py": "SetConversationSummaryService",
    "conversations/transfer_conversation_to_human_service.py": (
        "TransferConversationToHumanService"
    ),
    "conversations/update_message_status_service.py": "UpdateMessageStatusService",
    "customers/add_customer_tag_service.py": "AddCustomerTagService",
    "customers/archive_customer_service.py": "ArchiveCustomerService",
    "customers/create_customer_service.py": "CreateCustomerService",
    "customers/find_customer_by_phone_service.py": "FindCustomerByPhoneService",
    "customers/get_customer_service.py": "GetCustomerService",
    "customers/list_customers_service.py": "ListCustomersService",
    "customers/update_customer_service.py": "UpdateCustomerService",
    "customers/upsert_customer_from_whatsapp_service.py": (
        "UpsertCustomerFromWhatsAppService"
    ),
    "delivery/get_delivery_options_service.py": "GetDeliveryOptionsService",
    "inventory/adjust_stock_service.py": "AdjustStockService",
    "inventory/find_inventory_for_catalog_service.py": "FindInventoryForCatalogService",
    "inventory/get_inventory_service.py": "GetInventoryService",
    "inventory/get_or_create_inventory_service.py": "GetOrCreateInventoryService",
    "inventory/list_low_stock_inventory_service.py": "ListLowStockInventoryService",
    "inventory/list_inventory_history_service.py": "ListInventoryHistoryService",
    "inventory/reserve_stock_service.py": "ReserveStockService",
    "inventory/set_stock_service.py": "SetStockService",
    "inventory/update_minimum_inventory_service.py": "UpdateMinimumInventoryService",
    "knowledge/search_faq_service.py": "SearchFaqService",
    "knowledge/search_knowledge_service.py": "SearchKnowledgeService",
    "notifications/create_audit_log_service.py": "CreateAuditLogService",
    "notifications/create_notification_service.py": "CreateNotificationService",
    "outbox/dispatch_outbox_best_effort_service.py": "DispatchOutboxBestEffortService",
    "outbox/dispatch_outbox_entry_service.py": "DispatchOutboxEntryService",
    "outbox/dispatch_pending_outbox_service.py": "DispatchPendingOutboxService",
    "outbox/enqueue_outbox_task_service.py": "EnqueueOutboxTaskService",
    "products/archive_product_service.py": "ArchiveProductService",
    "products/archive_product_variant_service.py": "ArchiveProductVariantService",
    "products/create_product_service.py": "CreateProductService",
    "products/create_product_variant_service.py": "CreateProductVariantService",
    "products/list_products_service.py": "ListProductsService",
    "products/update_product_service.py": "UpdateProductService",
    "products/update_product_variant_service.py": "UpdateProductVariantService",
    "quota/enforce_inbound_quota_service.py": "EnforceInboundQuotaService",
    "whatsapp/check_whatsapp_connection_service.py": "CheckWhatsAppConnectionService",
    "whatsapp/disconnect_whatsapp_service.py": "DisconnectWhatsAppService",
    "whatsapp/generate_whatsapp_qrcode_service.py": "GenerateWhatsAppQrCodeService",
    "whatsapp/process_whatsapp_payload_service.py": "ProcessWhatsAppPayloadService",
    "whatsapp/send_whatsapp_text_service.py": "SendWhatsAppTextService",
}


def _use_case_modules() -> list[Path]:
    return sorted(
        path
        for path in SERVICE_ROOT.glob("*/*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    )


@pytest.mark.parametrize(
    ("relative_path", "expected_class"),
    sorted(EXPECTED_CASES.items()),
)
def test_expected_use_case_exists(relative_path: str, expected_class: str):
    path = SERVICE_ROOT / relative_path
    assert path.is_file(), f"Missing use-case module: {relative_path}"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert any(
        isinstance(node, ast.ClassDef) and node.name == expected_class
        for node in tree.body
    )


@pytest.mark.parametrize(
    "service_module",
    _use_case_modules(),
    ids=lambda path: path.relative_to(SERVICE_ROOT).as_posix(),
)
def test_each_use_case_module_exports_one_service_with_execute(service_module: Path):
    tree = ast.parse(
        service_module.read_text(encoding="utf-8"),
        filename=str(service_module),
    )
    service_classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Service")
    ]
    assert len(service_classes) == 1, (
        f"{service_module.relative_to(SERVICE_ROOT)} must define exactly one Service class"
    )
    service_class = service_classes[0]
    execute_methods = [
        node
        for node in service_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "execute"
    ]
    assert len(execute_methods) == 1, f"{service_class.name} must define execute()"

def test_every_domain_package_has_use_cases_and_an_init_module():
    domain_directories = sorted(
        path
        for path in SERVICE_ROOT.iterdir()
        if path.is_dir() and path.name != "__pycache__"
    )
    assert domain_directories
    for domain in domain_directories:
        assert (domain / "__init__.py").is_file()
        assert any(path.name != "__init__.py" for path in domain.glob("*.py"))


def test_compatibility_modules_do_not_define_multi_action_service_classes():
    """Only domain use-case modules may declare classes named ``*Service``."""

    for compatibility_module in SERVICE_ROOT.glob("*_service.py"):
        tree = ast.parse(
            compatibility_module.read_text(encoding="utf-8"),
            filename=str(compatibility_module),
        )
        service_classes = [
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Service")
        ]
        assert service_classes == [], (
            f"{compatibility_module.name} still defines aggregated Services: "
            f"{service_classes}"
        )
