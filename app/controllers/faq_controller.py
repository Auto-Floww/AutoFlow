"""Controller HTTP da base de perguntas frequentes e conhecimento da IA."""

from __future__ import annotations

import hashlib
import os
import threading
import zipfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from xml.etree import ElementTree

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models import FAQ, KnowledgeDocument
from app.controllers.http import coerce_bool, failure, model_dict, payload, record_audit, success
from app.tenant import current_company_id, roles_required, tenant_get_or_404


bp = Blueprint("faq", __name__, url_prefix="/faq")
_PDF_PARSE_LOCK = threading.Lock()

DEFAULT_DOCUMENT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_KNOWLEDGE_MAX_CHARS = 250_000
DEFAULT_PDF_MAX_PAGES = 100
DEFAULT_PDF_STREAM_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_DOCX_MAX_ENTRIES = 256
DEFAULT_DOCX_MAX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
DEFAULT_DOCX_MAX_COMPRESSION_RATIO = 100


def _faq_data(item: FAQ) -> dict:
    return model_dict(item, "id", "question", "answer", "category", "is_active", "priority", "updated_at")


def _limit(name: str, default: int) -> int:
    try:
        configured = current_app.config.get(name)
        value = int(configured if configured is not None else os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _read_upload_limited(upload, maximum: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.stream.read(min(64 * 1024, maximum + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise ValueError("O documento excede o limite de tamanho permitido")
    raw = b"".join(chunks)
    if not raw:
        raise ValueError("O documento esta vazio")
    upload._autoflow_validated_size = len(raw)
    return raw


def _validate_text(content: str, *, label: str = "O conteudo") -> str:
    if "\x00" in content:
        raise ValueError(f"{label} contem caracteres invalidos")
    maximum = _limit("KNOWLEDGE_MAX_TEXT_CHARS", DEFAULT_KNOWLEDGE_MAX_CHARS)
    if len(content) > maximum:
        raise ValueError(f"{label} excede o limite de texto permitido")
    return content.strip()


def _extract_docx(raw: bytes) -> str:
    if not raw.startswith(b"PK\x03\x04"):
        raise ValueError("O arquivo DOCX nao possui uma estrutura valida")
    max_entries = _limit("KNOWLEDGE_DOCX_MAX_ENTRIES", DEFAULT_DOCX_MAX_ENTRIES)
    max_uncompressed = _limit(
        "KNOWLEDGE_DOCX_MAX_UNCOMPRESSED_BYTES",
        DEFAULT_DOCX_MAX_UNCOMPRESSED_BYTES,
    )
    max_ratio = _limit(
        "KNOWLEDGE_DOCX_MAX_COMPRESSION_RATIO",
        DEFAULT_DOCX_MAX_COMPRESSION_RATIO,
    )
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > max_entries:
                raise ValueError("O DOCX possui arquivos internos demais")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("O DOCX possui entradas internas duplicadas")
            required = {"[Content_Types].xml", "word/document.xml"}
            if not required.issubset(names):
                raise ValueError("O arquivo DOCX nao possui uma estrutura valida")
            declared_size = 0
            compressed_size = 0
            for entry in entries:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts or entry.flag_bits & 0x1:
                    raise ValueError("O DOCX possui uma estrutura interna insegura")
                declared_size += entry.file_size
                compressed_size += entry.compress_size
                if declared_size > max_uncompressed:
                    raise ValueError("O DOCX excede o limite descomprimido permitido")
            if declared_size and (
                compressed_size <= 0 or declared_size / compressed_size > max_ratio
            ):
                raise ValueError("O DOCX possui taxa de compressao insegura")

            actual_size = 0
            document_xml = b""
            for entry in entries:
                if entry.is_dir():
                    continue
                captured: list[bytes] | None = [] if entry.filename == "word/document.xml" else None
                with archive.open(entry, "r") as member:
                    while True:
                        chunk = member.read(64 * 1024)
                        if not chunk:
                            break
                        actual_size += len(chunk)
                        if actual_size > max_uncompressed:
                            raise ValueError(
                                "O DOCX excede o limite descomprimido permitido"
                            )
                        if captured is not None:
                            captured.append(chunk)
                if captured is not None:
                    document_xml = b"".join(captured)
    except ValueError:
        raise
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError) as exc:
        raise ValueError("O arquivo DOCX esta corrompido") from exc

    if b"<!DOCTYPE" in document_xml or b"<!ENTITY" in document_xml:
        raise ValueError("O DOCX possui XML inseguro")
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError as exc:
        raise ValueError("O arquivo DOCX esta corrompido") from exc
    word_namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    total_chars = 0
    for paragraph in root.iter(f"{word_namespace}p"):
        value = "".join(
            node.text or "" for node in paragraph.iter(f"{word_namespace}t")
        ).strip()
        if value:
            total_chars += len(value) + 1
            if total_chars > _limit(
                "KNOWLEDGE_MAX_TEXT_CHARS", DEFAULT_KNOWLEDGE_MAX_CHARS
            ):
                raise ValueError("O texto extraido excede o limite permitido")
            paragraphs.append(value)
    return "\n".join(paragraphs)


def _extract_pdf(raw: bytes) -> tuple[str, int]:
    if not raw.startswith(b"%PDF-"):
        raise ValueError("O arquivo PDF nao possui uma assinatura valida")
    try:
        from pypdf import PdfReader, filters

        stream_limit = _limit(
            "KNOWLEDGE_PDF_MAX_STREAM_BYTES", DEFAULT_PDF_STREAM_MAX_BYTES
        )
        limit_names = (
            "ZLIB_MAX_OUTPUT_LENGTH",
            "LZW_MAX_OUTPUT_LENGTH",
            "RUN_LENGTH_MAX_OUTPUT_LENGTH",
            "JBIG2_MAX_OUTPUT_LENGTH",
            "MAX_ARRAY_BASED_STREAM_OUTPUT_LENGTH",
        )
        # pypdf exposes process-global decompression guards. Serialize the small
        # critical section so one request cannot weaken another request's limit.
        with _PDF_PARSE_LOCK:
            originals = {
                name: getattr(filters, name)
                for name in limit_names
                if hasattr(filters, name)
            }
            try:
                for name in originals:
                    setattr(filters, name, stream_limit)
                reader = PdfReader(BytesIO(raw), strict=False)
                if reader.is_encrypted:
                    raise ValueError("PDFs protegidos por senha nao sao aceitos")
                pages = len(reader.pages)
                if pages > _limit("KNOWLEDGE_PDF_MAX_PAGES", DEFAULT_PDF_MAX_PAGES):
                    raise ValueError("O PDF excede o limite de paginas permitido")
                extracted: list[str] = []
                total_chars = 0
                max_chars = _limit(
                    "KNOWLEDGE_MAX_TEXT_CHARS", DEFAULT_KNOWLEDGE_MAX_CHARS
                )
                for page in reader.pages:
                    text = page.extract_text() or ""
                    total_chars += len(text) + 2
                    if total_chars > max_chars:
                        raise ValueError("O texto extraido excede o limite permitido")
                    extracted.append(text)
            finally:
                for name, value in originals.items():
                    setattr(filters, name, value)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("O arquivo PDF esta corrompido ou e invalido") from exc
    return "\n\n".join(extracted), pages


def _extract_document(upload) -> tuple[str, str, int]:
    filename = secure_filename(upload.filename or "")
    extension = Path(filename).suffix.lower()
    raw = _read_upload_limited(
        upload,
        _limit("KNOWLEDGE_UPLOAD_MAX_BYTES", DEFAULT_DOCUMENT_MAX_BYTES),
    )
    pages = 0
    if extension == ".txt":
        try:
            content = raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("O arquivo TXT deve estar codificado em UTF-8") from exc
        pages = 1
    elif extension == ".pdf":
        content, pages = _extract_pdf(raw)
    elif extension == ".docx":
        content = _extract_docx(raw)
        pages = 0
    else:
        raise ValueError("Use um arquivo PDF, DOCX ou TXT")
    content = _validate_text(content, label="O texto extraido")
    if len(content) < 10:
        raise ValueError("Nao foi possivel extrair texto suficiente do documento")
    return content, extension.lstrip(".").upper(), pages


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    query = FAQ.for_company(company_id)
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(FAQ.question.ilike(pattern), FAQ.answer.ilike(pattern)))
    if category:
        query = query.filter(FAQ.category == category)
    faqs = query.order_by(FAQ.priority, FAQ.updated_at.desc()).all()
    for item in faqs:
        item.active = item.is_active
        item.updated_label = item.updated_at.strftime("%d/%m/%Y")
    categories = [
        value
        for value, in db.session.query(FAQ.category)
        .filter(FAQ.company_id == company_id, FAQ.category.is_not(None))
        .distinct()
        .order_by(FAQ.category)
        .all()
    ]
    documents = KnowledgeDocument.for_company(company_id).order_by(KnowledgeDocument.updated_at.desc()).all()
    document_views = [
        SimpleNamespace(
            id=item.id,
            name=item.title,
            title=item.title,
            extension=item.source_type.lower(),
            status=item.status,
            status_label={"READY": "Disponivel", "PROCESSING": "Processando", "FAILED": "Falhou"}.get(item.status, item.status),
            size_label=(item.metadata_json or {}).get("size_label", ""),
            pages_count=(item.metadata_json or {}).get("pages_count", 0),
            chunks_count=(item.metadata_json or {}).get("chunks_count", 0),
            created_label=item.created_at.strftime("%d/%m/%Y"),
        )
        for item in documents
    ]
    return render_template(
        "faq/index.html",
        faqs=faqs,
        categories=categories,
        faq_categories=categories,
        documents=document_views,
        filters={"q": search, "category": category},
    )


@bp.post("")
@bp.post("/create")
@login_required
@roles_required("ADMIN", "OWNER")
def create():
    data = payload()
    if data.get("id"):
        try:
            return update(int(data["id"]))
        except (TypeError, ValueError):
            return failure("FAQ invalida.", status=422)
    question = str(data.get("question", "")).strip()
    answer = str(data.get("answer", "")).strip()
    if len(question) < 3 or len(answer) < 3:
        return failure("Informe pergunta e resposta completas.", status=422)
    if len(question) > _limit("FAQ_MAX_QUESTION_CHARS", 1_000) or len(answer) > _limit(
        "FAQ_MAX_ANSWER_CHARS", 20_000
    ):
        return failure("Pergunta ou resposta excede o limite permitido.", status=422)
    item = FAQ(
        company_id=current_company_id(),
        question=question,
        answer=answer,
        category=str(data.get("category", "")).strip()[:100] or None,
        is_active=coerce_bool(data.get("active", data.get("is_active")), True),
        priority=int(data.get("priority", 100) or 100),
    )
    db.session.add(item)
    db.session.flush()
    record_audit("faq.create", item)
    db.session.commit()
    return success("FAQ adicionada.", data=_faq_data(item), endpoint="faq.index", status=201)


@bp.post("/<int:faq_id>")
@bp.put("/<int:faq_id>")
@bp.patch("/<int:faq_id>")
@login_required
@roles_required("ADMIN", "OWNER")
def update(faq_id: int):
    item = tenant_get_or_404(FAQ, faq_id)
    data = payload()
    if "question" in data:
        item.question = str(data["question"]).strip()
    if "answer" in data:
        item.answer = str(data["answer"]).strip()
    if len(item.question) < 3 or len(item.answer) < 3:
        return failure("Pergunta e resposta sao obrigatorias.", status=422)
    if len(item.question) > _limit("FAQ_MAX_QUESTION_CHARS", 1_000) or len(
        item.answer
    ) > _limit("FAQ_MAX_ANSWER_CHARS", 20_000):
        return failure("Pergunta ou resposta excede o limite permitido.", status=422)
    if "category" in data:
        item.category = str(data["category"]).strip()[:100] or None
    if "active" in data or "is_active" in data:
        item.is_active = coerce_bool(data.get("active", data.get("is_active")))
    if "priority" in data:
        item.priority = int(data["priority"])
    record_audit("faq.update", item)
    db.session.commit()
    return success("FAQ atualizada.", data=_faq_data(item), endpoint="faq.index")


@bp.delete("/<int:faq_id>")
@bp.post("/<int:faq_id>/archive")
@bp.post("/<int:faq_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete(faq_id: int):
    item = tenant_get_or_404(FAQ, faq_id)
    item.is_active = False
    record_audit("faq.archive", item)
    db.session.commit()
    return success("FAQ arquivada.", endpoint="faq.index")


@bp.post("/documents")
@login_required
@roles_required("ADMIN", "OWNER")
def create_document():
    data = payload()
    upload = request.files.get("document")
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    source_type = "TEXT"
    metadata = {}
    if upload and upload.filename:
        try:
            content, source_type, pages = _extract_document(upload)
        except ValueError as exc:
            return failure(str(exc), status=422)
        except Exception:
            # Parser internals and file paths must never reach the response.
            current_app.logger.exception("Falha inesperada ao validar documento")
            return failure("Documento invalido ou corrompido.", status=422)
        title = title or Path(secure_filename(upload.filename)).stem
        metadata = {
            "original_filename": secure_filename(upload.filename),
            "size_bytes": getattr(upload, "_autoflow_validated_size", 0),
            "size_label": f"{len(content.encode('utf-8')) / 1024:.1f} KB",
            "pages_count": pages,
            "chunks_count": max(1, len(content) // 1200),
        }
    else:
        try:
            content = _validate_text(content, label="O conteudo")
        except ValueError as exc:
            return failure(str(exc), status=422)
    if len(title) < 2 or len(content) < 10:
        return failure("Informe titulo e conteudo do documento.", status=422)
    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    existing = KnowledgeDocument.for_company(current_company_id()).filter_by(checksum=checksum).first()
    if existing:
        return failure("Este conteudo ja esta na base.", status=409)
    document = KnowledgeDocument(
        company_id=current_company_id(),
        title=title[:255],
        content=content,
        source_type=source_type,
        checksum=checksum,
        status="READY",
        is_active=True,
        metadata_json=metadata,
    )
    try:
        db.session.add(document)
        db.session.flush()
        record_audit("knowledge_document.create", document)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return failure("Este conteudo ja esta na base.", status=409)
    return success("Documento adicionado a base da IA.", data=model_dict(document, "id", "title", "status"), status=201)


@bp.delete("/documents/<int:document_id>")
@bp.post("/documents/<int:document_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete_document(document_id: int):
    document = tenant_get_or_404(KnowledgeDocument, document_id)
    document.is_active = False
    record_audit("knowledge_document.archive", document)
    db.session.commit()
    return success("Documento arquivado.")


@bp.get("/search")
@login_required
def search():
    term = request.args.get("q", "").strip()
    if not term:
        return jsonify(results=[])
    company_id = current_company_id()
    pattern = f"%{term}%"
    faqs = FAQ.for_company(company_id).filter(
        FAQ.is_active.is_(True), or_(FAQ.question.ilike(pattern), FAQ.answer.ilike(pattern))
    ).limit(10).all()
    docs = KnowledgeDocument.for_company(company_id).filter(
        KnowledgeDocument.is_active.is_(True),
        KnowledgeDocument.status == "READY",
        or_(KnowledgeDocument.title.ilike(pattern), KnowledgeDocument.content.ilike(pattern)),
    ).limit(10).all()
    return jsonify(
        results=[
            {"type": "faq", **_faq_data(item)} for item in faqs
        ]
        + [
            {"type": "document", **model_dict(item, "id", "title", "updated_at")}
            for item in docs
        ]
    )


class FaqController:
    """Handlers HTTP do dominio de FAQ e conhecimento."""

    index = staticmethod(index)
    create = staticmethod(create)
    update = staticmethod(update)
    delete = staticmethod(delete)
    create_document = staticmethod(create_document)
    delete_document = staticmethod(delete_document)
    search = staticmethod(search)


for _endpoint, _handler in {
    "index": FaqController.index,
    "create": FaqController.create,
    "update": FaqController.update,
    "delete": FaqController.delete,
    "create_document": FaqController.create_document,
    "delete_document": FaqController.delete_document,
    "search": FaqController.search,
}.items():
    bp.view_functions[_endpoint] = _handler

del _endpoint, _handler
