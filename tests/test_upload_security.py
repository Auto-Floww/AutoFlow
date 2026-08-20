"""Security regression tests for knowledge and product uploads."""

from __future__ import annotations

import struct
import zipfile
import zlib
from io import BytesIO

from flask import g
from pypdf import PdfWriter

from app.extensions import db
from app.models import KnowledgeDocument, Product


AJAX_HEADERS = {"X-Requested-With": "XMLHttpRequest"}


def _chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def _png() -> bytes:
    pixels = b"\x00\x00\x00\x00\xff"  # filter byte + one RGBA pixel
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(pixels))
        + _chunk(b"IEND", b"")
    )


def _docx(text: str, *, extra_entries: int = 0) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/'
                'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'
                f"{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
        for index in range(extra_entries):
            archive.writestr(f"word/media/item-{index}.bin", b"x")
    return output.getvalue()


def _pdf(*, pages: int = 1, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("segredo")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _product_payload(image: bytes, filename: str, *, sku: str, mimetype: str):
    return {
        "name": f"Produto {sku}",
        "sku": sku,
        "price": "10.00",
        "image": (BytesIO(image), filename, mimetype),
    }


def _visible_uploads(root, company_id: int):
    tenant_dir = root / str(company_id)
    if not tenant_dir.exists():
        return []
    return [path for path in tenant_dir.iterdir() if not path.name.startswith(".")]


def test_manual_and_extracted_knowledge_respect_text_limit(
    client, app, login_as, tenant_user
):
    login_as(tenant_user)
    app.config["KNOWLEDGE_MAX_TEXT_CHARS"] = 32

    manual = client.post(
        "/faq/documents",
        json={"title": "Manual extenso", "content": "A" * 33},
        headers=AJAX_HEADERS,
    )
    extracted = client.post(
        "/faq/documents",
        data={
            "title": "TXT extenso",
            "document": (BytesIO(b"B" * 33), "base.txt", "text/plain"),
        },
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert manual.status_code == extracted.status_code == 422
    assert KnowledgeDocument.query.count() == 0


def test_docx_zip_bomb_and_excess_entries_are_rejected(
    client, app, login_as, tenant_user
):
    login_as(tenant_user)
    app.config.update(
        KNOWLEDGE_DOCX_MAX_UNCOMPRESSED_BYTES=1_024,
        KNOWLEDGE_DOCX_MAX_COMPRESSION_RATIO=20,
        KNOWLEDGE_DOCX_MAX_ENTRIES=2,
    )

    expanded = client.post(
        "/faq/documents",
        data={"document": (BytesIO(_docx("A" * 4_000)), "bomba.docx")},
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    too_many = client.post(
        "/faq/documents",
        data={"document": (BytesIO(_docx("Conteudo seguro", extra_entries=1)), "muitos.docx")},
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert expanded.status_code == too_many.status_code == 422
    assert KnowledgeDocument.query.count() == 0


def test_valid_docx_is_extracted_after_archive_preflight(
    client, login_as, tenant_user
):
    login_as(tenant_user)
    response = client.post(
        "/faq/documents",
        data={
            "title": "Politica segura",
            "document": (
                BytesIO(_docx("Conteudo confiavel para a base de conhecimento")),
                "politica.docx",
            ),
        },
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    document = KnowledgeDocument.query.one()
    assert document.source_type == "DOCX"
    assert "Conteudo confiavel" in document.content


def test_pdf_page_limit_encryption_and_corruption_are_safe(
    client, app, login_as, tenant_user
):
    login_as(tenant_user)
    app.config["KNOWLEDGE_PDF_MAX_PAGES"] = 1
    cases = [
        (_pdf(pages=2), "paginas.pdf"),
        (_pdf(encrypted=True), "protegido.pdf"),
        (b"%PDF-conteudo-corrompido", "corrompido.pdf"),
    ]

    for raw, filename in cases:
        response = client.post(
            "/faq/documents",
            data={"document": (BytesIO(raw), filename, "application/pdf")},
            headers=AJAX_HEADERS,
            content_type="multipart/form-data",
        )
        assert response.status_code == 422
        body = response.get_json()["message"].lower()
        assert "traceback" not in body and "segredo" not in body
    assert KnowledgeDocument.query.count() == 0


def test_valid_png_is_accepted_from_magic_not_declared_mimetype(
    client, app, tmp_path, login_as, tenant_user
):
    upload_root = tmp_path / "persistent-products"
    app.config.update(
        PRODUCT_UPLOAD_DIR=str(upload_root),
        PRODUCT_UPLOAD_URL_PREFIX="/media/products",
    )
    login_as(tenant_user)

    response = client.post(
        "/products",
        data=_product_payload(_png(), "real.png", sku="IMG-001", mimetype="text/plain"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    product = Product.query.filter_by(sku="IMG-001").one()
    assert product.image_url.startswith(f"/media/products/{tenant_user.company_id}/")
    files = _visible_uploads(upload_root, tenant_user.company_id)
    assert len(files) == 1 and files[0].suffix == ".png"
    assert not list((upload_root / str(tenant_user.company_id)).glob(".upload-*"))


def test_spoofed_or_extension_mismatched_image_leaves_no_file(
    client, app, tmp_path, login_as, tenant_user
):
    upload_root = tmp_path / "products"
    app.config["PRODUCT_UPLOAD_DIR"] = str(upload_root)
    login_as(tenant_user)

    spoofed = client.post(
        "/products",
        data=_product_payload(b"nao-e-png", "falso.png", sku="BAD-001", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    mismatch = client.post(
        "/products",
        data=_product_payload(_png(), "falso.jpg", sku="BAD-002", mimetype="image/jpeg"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    corrupted_png = bytearray(_png())
    corrupted_png[-8] ^= 0x01
    corrupted = client.post(
        "/products",
        data=_product_payload(
            bytes(corrupted_png), "corrupt.png", sku="BAD-003", mimetype="image/png"
        ),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert spoofed.status_code == mismatch.status_code == corrupted.status_code == 422
    assert Product.query.count() == 0
    assert _visible_uploads(upload_root, tenant_user.company_id) == []
    assert not list((upload_root / str(tenant_user.company_id)).glob(".upload-*"))


def test_image_quota_is_enforced_independently_per_tenant(
    client, app, tmp_path, login_as, tenant_user, user_factory
):
    upload_root = tmp_path / "quota"
    image = _png()
    app.config.update(
        PRODUCT_UPLOAD_DIR=str(upload_root),
        PRODUCT_IMAGE_TENANT_QUOTA_BYTES=len(image) + 10,
    )
    login_as(tenant_user)

    first = client.post(
        "/products",
        data=_product_payload(image, "one.png", sku="Q-ONE", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    second = client.post(
        "/products",
        data=_product_payload(image, "two.png", sku="Q-TWO", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    other_user = user_factory(email="other-upload@example.com")
    login_as(other_user)
    # The suite keeps one outer app context for speed; clear Flask-Login's cached
    # proxy when switching identities inside the same test.
    g.pop("_login_user", None)
    other = client.post(
        "/products",
        data=_product_payload(image, "other.png", sku="Q-OTHER", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert first.status_code == other.status_code == 201, other.get_json()
    assert second.status_code == 422
    assert len(_visible_uploads(upload_root, tenant_user.company_id)) == 1
    assert len(_visible_uploads(upload_root, other_user.company_id)) == 1


def test_database_or_final_move_failure_cleans_temporary_file(
    client, app, tmp_path, login_as, tenant_user, monkeypatch
):
    upload_root = tmp_path / "failures"
    app.config["PRODUCT_UPLOAD_DIR"] = str(upload_root)
    login_as(tenant_user)
    real_commit = db.session.commit

    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    database_failure = client.post(
        "/products",
        data=_product_payload(_png(), "db.png", sku="FAIL-DB", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )
    monkeypatch.setattr(db.session, "commit", real_commit)

    assert database_failure.status_code == 500
    assert _visible_uploads(upload_root, tenant_user.company_id) == []
    assert not list((upload_root / str(tenant_user.company_id)).glob(".upload-*"))

    monkeypatch.setattr(
        "app.routes.products.os.replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk down")),
    )
    move_failure = client.post(
        "/products",
        data=_product_payload(_png(), "move.png", sku="FAIL-MOVE", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert move_failure.status_code == 500
    saved = Product.query.filter_by(sku="FAIL-MOVE").one()
    assert saved.image_url is None
    assert _visible_uploads(upload_root, tenant_user.company_id) == []
    assert not list((upload_root / str(tenant_user.company_id)).glob(".upload-*"))


def test_image_receives_final_name_only_after_database_commit(
    client, app, tmp_path, login_as, tenant_user, monkeypatch
):
    from app.routes.products import PendingImage

    upload_root = tmp_path / "commit-order"
    app.config["PRODUCT_UPLOAD_DIR"] = str(upload_root)
    login_as(tenant_user)
    state = {"committed": False, "finalized": False}
    real_commit = db.session.commit
    real_finalize = PendingImage.finalize

    def tracked_commit():
        real_commit()
        state["committed"] = True

    def tracked_finalize(pending):
        assert state["committed"] is True
        assert pending.temporary_path.exists()
        assert not pending.final_path.exists()
        real_finalize(pending)
        state["finalized"] = True

    monkeypatch.setattr(db.session, "commit", tracked_commit)
    monkeypatch.setattr(PendingImage, "finalize", tracked_finalize)

    response = client.post(
        "/products",
        data=_product_payload(_png(), "ordered.png", sku="ORDERED", mimetype="image/png"),
        headers=AJAX_HEADERS,
        content_type="multipart/form-data",
    )

    assert response.status_code == 201
    assert state == {"committed": True, "finalized": True}
    assert len(_visible_uploads(upload_root, tenant_user.company_id)) == 1
