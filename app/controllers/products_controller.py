"""Controller HTTP do catalogo de produtos e variantes."""

from __future__ import annotations

import contextlib
import os
import struct
import tempfile
import threading
import zlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from flask import Blueprint, abort, current_app, jsonify, render_template, request, send_from_directory
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from app.extensions import db, limiter
from app.models import Product, ProductVariant
from app.controllers.http import coerce_bool, failure, model_dict, payload, record_audit, success
from app.services.exceptions import DomainError
from app.services.products import (
    ArchiveProductService,
    ArchiveProductVariantService,
    CreateProductService,
    CreateProductVariantService,
    ListProductsService,
    UpdateProductService,
    UpdateProductVariantService,
)
from app.tenant import current_company_id, roles_required, tenant_get_or_404


bp = Blueprint("products", __name__, url_prefix="/products")
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
DEFAULT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_IMAGE_MAX_DIMENSION = 8_192
DEFAULT_IMAGE_MAX_PIXELS = 25_000_000
DEFAULT_IMAGE_MAX_DECODED_BYTES = 64 * 1024 * 1024
DEFAULT_TENANT_IMAGE_QUOTA_BYTES = 100 * 1024 * 1024

_LOCAL_UPLOAD_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_UPLOAD_LOCKS_GUARD = threading.Lock()


def _upload_limit(name: str, default: int) -> int:
    try:
        configured = current_app.config.get(name)
        value = int(configured if configured is not None else os.getenv(name, default))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _validate_dimensions(width: int, height: int) -> tuple[int, int]:
    maximum = _upload_limit("PRODUCT_IMAGE_MAX_DIMENSION", DEFAULT_IMAGE_MAX_DIMENSION)
    max_pixels = _upload_limit("PRODUCT_IMAGE_MAX_PIXELS", DEFAULT_IMAGE_MAX_PIXELS)
    if width <= 0 or height <= 0 or width > maximum or height > maximum:
        raise ValueError("Dimensoes da imagem excedem o limite permitido")
    if width * height > max_pixels:
        raise ValueError("A imagem possui pixels demais")
    return width, height


def _decompress_bounded(compressed: bytes, maximum: int) -> bytes:
    try:
        decompressor = zlib.decompressobj()
        decoded = decompressor.decompress(compressed, maximum + 1)
        if len(decoded) > maximum or decompressor.unconsumed_tail:
            raise ValueError("A imagem descomprime para um tamanho inseguro")
        remaining = maximum + 1 - len(decoded)
        if remaining > 0:
            decoded += decompressor.flush(remaining)
        if len(decoded) > maximum or not decompressor.eof or decompressor.unused_data:
            raise ValueError("Os dados comprimidos da imagem sao invalidos")
        return decoded
    except zlib.error as exc:
        raise ValueError("Os dados comprimidos da imagem estao corrompidos") from exc


def _validate_png(raw: bytes) -> tuple[int, int]:
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Assinatura PNG invalida")
    offset = 8
    chunks = 0
    width = height = bit_depth = color_type = interlace = 0
    saw_header = saw_data = saw_end = False
    idat_parts: list[bytes] = []
    while offset < len(raw):
        chunks += 1
        if chunks > 2_048 or offset + 12 > len(raw):
            raise ValueError("Estrutura PNG invalida")
        length = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunk_type = raw[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(raw):
            raise ValueError("Estrutura PNG truncada")
        data = raw[offset + 8 : offset + 8 + length]
        expected_crc = struct.unpack(">I", raw[offset + 8 + length : end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            raise ValueError("A imagem PNG possui dados corrompidos")
        if not saw_header and chunk_type != b"IHDR":
            raise ValueError("Cabecalho PNG ausente")
        if chunk_type == b"IHDR":
            if saw_header or length != 13:
                raise ValueError("Cabecalho PNG invalido")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if compression != 0 or filtering != 0 or interlace not in {0, 1}:
                raise ValueError("Parametros PNG nao suportados")
            valid_depths = {
                0: {1, 2, 4, 8, 16},
                2: {8, 16},
                3: {1, 2, 4, 8},
                4: {8, 16},
                6: {8, 16},
            }
            if bit_depth not in valid_depths.get(color_type, set()):
                raise ValueError("Profundidade de cor PNG invalida")
            _validate_dimensions(width, height)
            saw_header = True
        elif chunk_type == b"IDAT":
            if not saw_header or saw_end:
                raise ValueError("Ordem de chunks PNG invalida")
            saw_data = True
            idat_parts.append(data)
        elif chunk_type == b"IEND":
            if length != 0 or not saw_data:
                raise ValueError("Final PNG invalido")
            saw_end = True
            offset = end
            break
        offset = end
    if not saw_header or not saw_data or not saw_end or offset != len(raw):
        raise ValueError("A imagem PNG esta incompleta")
    decoded_limit = _upload_limit(
        "PRODUCT_IMAGE_MAX_DECODED_BYTES", DEFAULT_IMAGE_MAX_DECODED_BYTES
    )
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
    expected_scanlines = height * (1 + ((width * channels * bit_depth + 7) // 8))
    if interlace == 0:
        maximum = min(decoded_limit, expected_scanlines)
        decoded = _decompress_bounded(b"".join(idat_parts), maximum)
        if len(decoded) != expected_scanlines:
            raise ValueError("Os pixels PNG estao truncados")
        row_size = 1 + ((width * channels * bit_depth + 7) // 8)
        if any(decoded[index] > 4 for index in range(0, len(decoded), row_size)):
            raise ValueError("Filtro PNG invalido")
    else:
        _decompress_bounded(b"".join(idat_parts), decoded_limit)
    return width, height


def _validate_jpeg(raw: bytes) -> tuple[int, int]:
    if len(raw) < 4 or raw[:2] != b"\xff\xd8":
        raise ValueError("Assinatura JPEG invalida")
    offset = 2
    width = height = 0
    saw_scan = saw_end = False
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    markers = 0
    while offset < len(raw):
        if raw[offset] != 0xFF:
            raise ValueError("Estrutura JPEG invalida")
        while offset < len(raw) and raw[offset] == 0xFF:
            offset += 1
        if offset >= len(raw):
            break
        marker = raw[offset]
        offset += 1
        markers += 1
        if markers > 8_192:
            raise ValueError("A imagem JPEG possui segmentos demais")
        if marker == 0xD9:
            saw_end = True
            break
        if marker in {0x01, *range(0xD0, 0xD8)}:
            continue
        if marker == 0x00 or offset + 2 > len(raw):
            raise ValueError("Estrutura JPEG invalida")
        segment_length = struct.unpack(">H", raw[offset : offset + 2])[0]
        if segment_length < 2 or offset + segment_length > len(raw):
            raise ValueError("Segmento JPEG truncado")
        segment = raw[offset + 2 : offset + segment_length]
        offset += segment_length
        if marker in sof_markers:
            if len(segment) < 6:
                raise ValueError("Cabecalho JPEG invalido")
            height = struct.unpack(">H", segment[1:3])[0]
            width = struct.unpack(">H", segment[3:5])[0]
            _validate_dimensions(width, height)
        if marker == 0xDA:
            if not width or not height:
                raise ValueError("JPEG sem dimensoes validas")
            saw_scan = True
            while offset < len(raw):
                marker_start = raw.find(b"\xff", offset)
                if marker_start < 0 or marker_start + 1 >= len(raw):
                    offset = len(raw)
                    break
                next_byte = raw[marker_start + 1]
                if next_byte == 0x00 or 0xD0 <= next_byte <= 0xD7:
                    offset = marker_start + 2
                    continue
                if next_byte == 0xFF:
                    offset = marker_start + 1
                    continue
                offset = marker_start
                break
    if not width or not height or not saw_scan or not saw_end:
        raise ValueError("A imagem JPEG esta incompleta ou corrompida")
    if raw[offset:].strip(b"\x00\t\r\n "):
        raise ValueError("A imagem JPEG possui dados inesperados apos o final")
    return width, height


def _validate_webp(raw: bytes) -> tuple[int, int]:
    if len(raw) < 20 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise ValueError("Assinatura WebP invalida")
    if struct.unpack("<I", raw[4:8])[0] + 8 != len(raw):
        raise ValueError("Estrutura WebP truncada")
    offset = 12
    width = height = 0
    chunks = 0
    saw_image_payload = False
    while offset < len(raw):
        chunks += 1
        if chunks > 2_048 or offset + 8 > len(raw):
            raise ValueError("Estrutura WebP invalida")
        chunk_type = raw[offset : offset + 4]
        length = struct.unpack("<I", raw[offset + 4 : offset + 8])[0]
        data_start = offset + 8
        data_end = data_start + length
        padded_end = data_end + (length & 1)
        if padded_end > len(raw):
            raise ValueError("Chunk WebP truncado")
        data = raw[data_start:data_end]
        if chunk_type == b"VP8 ":
            if len(data) < 10 or data[3:6] != b"\x9d\x01\x2a":
                raise ValueError("Payload WebP VP8 invalido")
            width = struct.unpack("<H", data[6:8])[0] & 0x3FFF
            height = struct.unpack("<H", data[8:10])[0] & 0x3FFF
            saw_image_payload = True
        elif chunk_type == b"VP8L":
            if len(data) < 5 or data[0] != 0x2F:
                raise ValueError("Payload WebP VP8L invalido")
            bits = int.from_bytes(data[1:5], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            saw_image_payload = True
        elif chunk_type == b"VP8X":
            if len(data) != 10:
                raise ValueError("Cabecalho WebP estendido invalido")
            width = int.from_bytes(data[4:7], "little") + 1
            height = int.from_bytes(data[7:10], "little") + 1
        elif chunk_type in {b"ANIM", b"ANMF"}:
            saw_image_payload = True
        offset = padded_end
    if offset != len(raw) or not width or not height or not saw_image_payload:
        raise ValueError("A imagem WebP esta incompleta")
    return _validate_dimensions(width, height)


def _detect_and_validate_image(raw: bytes) -> tuple[str, int, int]:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _validate_png(raw)
        return "png", width, height
    if raw.startswith(b"\xff\xd8"):
        width, height = _validate_jpeg(raw)
        return "jpg", width, height
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        width, height = _validate_webp(raw)
        return "webp", width, height
    raise ValueError("O conteudo enviado nao e uma imagem PNG, JPEG ou WebP valida")


@contextlib.contextmanager
def _tenant_quota_lock(tenant_dir: Path):
    lock_path = tenant_dir / ".quota.lock"
    lock_key = str(lock_path.resolve())
    with _LOCAL_UPLOAD_LOCKS_GUARD:
        local_lock = _LOCAL_UPLOAD_LOCKS.setdefault(lock_key, threading.Lock())
    local_lock.acquire()
    handle = None
    try:
        handle = lock_path.open("a+b")
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        if handle is not None:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        local_lock.release()


def _upload_root_and_prefix() -> tuple[Path, str]:
    configured = str(
        current_app.config.get("PRODUCT_UPLOAD_DIR")
        or os.getenv("PRODUCT_UPLOAD_DIR", "")
    ).strip()
    if configured:
        root = Path(configured).expanduser()
        if not root.is_absolute():
            root = Path(current_app.instance_path) / root
    else:
        root = Path(current_app.instance_path) / "uploads" / "products"
    root.mkdir(parents=True, exist_ok=True)
    prefix = str(
        current_app.config.get("PRODUCT_UPLOAD_URL_PREFIX")
        or os.getenv("PRODUCT_UPLOAD_URL_PREFIX", "/products/uploads")
    ).strip()
    if not prefix or not (prefix.startswith("/") or prefix.startswith(("http://", "https://"))):
        raise RuntimeError("PRODUCT_UPLOAD_URL_PREFIX invalido")
    return root.resolve(), prefix.rstrip("/")


@bp.get("/uploads/<int:company_id>/<path:filename>")
@login_required
def uploaded_image(company_id: int, filename: str):
    """Entrega uploads locais somente ao tenant dono; CDNs usam prefixo externo."""

    if company_id != current_company_id() or Path(filename).name != filename:
        abort(404)
    root, prefix = _upload_root_and_prefix()
    expected_url = f"{prefix}/{company_id}/{filename}"
    if Product.for_company(company_id).filter_by(image_url=expected_url).first() is None:
        abort(404)
    response = send_from_directory(
        root / str(company_id), filename, conditional=True, max_age=3600
    )
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


def _managed_image_path(image_url: str | None, company_id: int, root: Path, prefix: str) -> Path | None:
    if not image_url:
        return None
    expected = f"{prefix}/{company_id}/"
    if not image_url.startswith(expected):
        return None
    filename = image_url[len(expected) :]
    if not filename or Path(filename).name != filename:
        return None
    candidate = (root / str(company_id) / filename).resolve()
    tenant_root = (root / str(company_id)).resolve()
    return candidate if candidate.parent == tenant_root else None


@dataclass
class PendingImage:
    temporary_path: Path
    final_path: Path
    public_url: str
    width: int
    height: int
    size_bytes: int
    _lock_context: object = field(repr=False)
    replaced_path: Path | None = None
    _released: bool = field(default=False, init=False, repr=False)

    def _release(self) -> None:
        if not self._released:
            self._lock_context.__exit__(None, None, None)
            self._released = True

    def finalize(self) -> None:
        try:
            os.replace(self.temporary_path, self.final_path)
            if self.replaced_path and self.replaced_path != self.final_path:
                try:
                    self.replaced_path.unlink(missing_ok=True)
                except OSError:
                    current_app.logger.warning(
                        "Nao foi possivel remover imagem de produto substituida"
                    )
        finally:
            self._release()

    def cleanup(self) -> None:
        try:
            try:
                self.temporary_path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.warning("Nao foi possivel remover upload temporario")
        finally:
            self._release()


def _prepare_image(*, replacing_url: str | None = None) -> PendingImage | None:
    upload = request.files.get("image")
    if not upload or not upload.filename:
        return None
    filename = secure_filename(upload.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Use uma imagem PNG, JPG ou WebP")

    company_id = current_company_id()
    root, prefix = _upload_root_and_prefix()
    tenant_dir = root / str(company_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    if tenant_dir.resolve().parent != root:
        raise RuntimeError("Diretorio de upload do tenant e inseguro")
    lock_context = _tenant_quota_lock(tenant_dir)
    lock_entered = False
    temporary_path: Path | None = None
    try:
        lock_context.__enter__()
        lock_entered = True
        maximum = _upload_limit("PRODUCT_IMAGE_MAX_BYTES", DEFAULT_IMAGE_MAX_BYTES)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".upload-",
            suffix=".tmp",
            dir=tenant_dir,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            total = 0
            while True:
                chunk = upload.stream.read(min(64 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise ValueError("A imagem excede o limite de tamanho permitido")
                temporary.write(chunk)
            temporary.flush()
            os.fsync(temporary.fileno())
        if not total:
            raise ValueError("A imagem esta vazia")
        raw = temporary_path.read_bytes()
        detected, width, height = _detect_and_validate_image(raw)
        expected = "jpg" if extension in {"jpg", "jpeg"} else extension
        if detected != expected:
            raise ValueError("A extensao do arquivo nao corresponde ao conteudo da imagem")

        replaced_path = _managed_image_path(
            replacing_url, company_id, root, prefix
        )
        if replaced_path and Product.for_company(company_id).filter(
            Product.image_url == replacing_url
        ).count() > 1:
            replaced_path = None
        used = 0
        with os.scandir(tenant_dir) as entries:
            for entry in entries:
                if entry.name.startswith(".") or not entry.is_file(follow_symlinks=False):
                    continue
                used += entry.stat(follow_symlinks=False).st_size
        credit = (
            replaced_path.stat().st_size
            if replaced_path and replaced_path.is_file() and not replaced_path.is_symlink()
            else 0
        )
        quota = _upload_limit(
            "PRODUCT_IMAGE_TENANT_QUOTA_BYTES", DEFAULT_TENANT_IMAGE_QUOTA_BYTES
        )
        if used - credit + total > quota:
            raise ValueError("A empresa atingiu a cota de imagens de produtos")
        stored_name = f"{uuid4().hex}.{detected}"
        final_path = tenant_dir / stored_name
        return PendingImage(
            temporary_path=temporary_path,
            final_path=final_path,
            public_url=f"{prefix}/{company_id}/{stored_name}",
            width=width,
            height=height,
            size_bytes=total,
            replaced_path=replaced_path,
            _lock_context=lock_context,
        )
    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        if lock_entered:
            lock_context.__exit__(None, None, None)
        raise


def _money(value, *, optional: bool = False):
    if optional and value in {None, ""}:
        return None
    try:
        raw = str(value or "0").replace("R$", "").replace(" ", "")
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError("Preco invalido") from exc
    if result < 0:
        raise ValueError("Preco nao pode ser negativo")
    return result.quantize(Decimal("0.01"))


def _product_data(product: Product) -> dict:
    return {
        **model_dict(
            product,
            "id",
            "name",
            "description",
            "sku",
            "category",
            "brand",
            "price",
            "promotional_price",
            "image_url",
            "is_active",
            "created_at",
        ),
        "effective_price": str(product.effective_price),
        "stock": product.inventory.available_quantity if product.inventory else None,
        "variants": [
            {
                **model_dict(
                    variant,
                    "id",
                    "name",
                    "color",
                    "size",
                    "sku",
                    "price",
                    "is_active",
                ),
                "stock": variant.inventory.available_quantity if variant.inventory else 0,
            }
            for variant in product.variants
        ],
    }


@bp.get("")
@login_required
def index():
    company_id = current_company_id()
    search = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    active = request.args.get("active", "").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    active_filter = None
    if active in {"true", "1", "active"}:
        active_filter = True
    elif active in {"false", "0", "inactive"}:
        active_filter = False
    query = ListProductsService().execute(
        company_id,
        search=search,
        category=category,
        active=active_filter,
    )
    pagination = query.paginate(
        page=page, per_page=24, error_out=False
    )
    categories = [
        value
        for value, in db.session.query(Product.category)
        .filter(Product.company_id == company_id, Product.category.is_not(None))
        .distinct()
        .order_by(Product.category)
        .all()
    ]
    active_count = Product.for_company(company_id).filter(Product.is_active.is_(True)).count()
    low_stock = 0
    for product in pagination.items:
        inventories = [variant.inventory for variant in product.variants if variant.inventory]
        if not inventories and product.inventory:
            inventories = [product.inventory]
        product.stock = sum(item.available_quantity for item in inventories)
        product.minimum_stock = sum(item.minimum_quantity for item in inventories)
        product.price_label = "R$ " + f"{product.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        product.promotional_price_label = (
            "R$ " + f"{product.promotional_price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            if product.promotional_price is not None
            else None
        )
        if product.stock <= product.minimum_stock:
            low_stock += 1
    product_stats = SimpleNamespace(
        total=Product.for_company(company_id).count(),
        active=active_count,
        low_stock=low_stock,
        ai_queries=0,
    )
    return render_template(
        "products/index.html",
        products=pagination.items,
        pagination=pagination,
        product_pagination=pagination,
        product_stats=product_stats,
        categories=categories,
        filters={"q": search, "category": category, "active": active},
    )


@bp.post("")
@bp.post("/create")
@login_required
@roles_required("ADMIN", "OWNER")
@limiter.limit("30 per minute")
def create():
    data = payload()
    if data.get("id"):
        try:
            return update(int(data["id"]))
        except (TypeError, ValueError):
            return failure("Produto invalido.", status=422)
    pending_image: PendingImage | None = None
    try:
        pending_image = _prepare_image()
        colors = request.form.getlist("variant_color[]")
        sizes = request.form.getlist("variant_size[]")
        skus = request.form.getlist("variant_sku[]")
        prices = request.form.getlist("variant_price[]")
        stocks = request.form.getlist("variant_stock[]")
        variant_count = max(map(len, (colors, sizes, skus, prices, stocks)), default=0)
        variants = []
        for index in range(variant_count):
            color = colors[index].strip() if index < len(colors) else ""
            size = sizes[index].strip() if index < len(sizes) else ""
            sku = skus[index].strip() if index < len(skus) else ""
            if not any((color, size, sku)):
                continue
            variants.append(
                {
                    "name": " / ".join(filter(None, (color, size))) or None,
                    "color": color,
                    "size": size,
                    "sku": sku,
                    "price": _money(
                        prices[index].strip() if index < len(prices) else "",
                        optional=True,
                    ),
                    "stock": int(stocks[index] or 0) if index < len(stocks) else 0,
                }
            )
        product = CreateProductService().execute(
            current_company_id(),
            name=str(data.get("name", "")),
            description=data.get("description"),
            sku=data.get("sku"),
            category=data.get("category"),
            brand=data.get("brand"),
            price=_money(data.get("price")),
            promotional_price=_money(data.get("promotional_price"), optional=True),
            image_url=(
                pending_image.public_url
                if pending_image
                else str(data.get("image_url", "")).strip() or None
            ),
            is_active=coerce_bool(data.get("active", data.get("is_active")), True),
            minimum_quantity=max(0, int(data.get("minimum_quantity", 0) or 0)),
            initial_stock=int(data.get("stock", data.get("quantity", 0)) or 0),
            variants=variants,
            actor_user_id=current_user.id,
            commit=False,
        )
        record_audit("product.create", product)
        db.session.commit()
    except (ValueError, DomainError, IntegrityError) as exc:
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        message = exc.message if isinstance(exc, DomainError) else str(exc)
        if isinstance(exc, IntegrityError):
            message = "Ja existe um produto com este SKU."
        return failure(message or "Dados do produto invalidos.", status=409 if isinstance(exc, IntegrityError) else 422)
    except (OSError, RuntimeError):
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        current_app.logger.exception("Falha ao preparar upload de imagem do produto")
        return failure("Nao foi possivel armazenar a imagem do produto.", status=500)
    except Exception:
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        current_app.logger.exception("Falha inesperada ao criar produto com imagem")
        return failure("Nao foi possivel criar o produto.", status=500)
    if pending_image:
        try:
            pending_image.finalize()
        except OSError:
            pending_image.cleanup()
            current_app.logger.exception("Falha ao finalizar imagem apos commit do produto")
            product.image_url = None
            db.session.commit()
            return failure("Nao foi possivel concluir o armazenamento da imagem.", status=500)
    return success("Produto criado.", data=_product_data(product), endpoint="products.index", status=201)


@bp.get("/<int:product_id>")
@login_required
def detail(product_id: int):
    product = tenant_get_or_404(Product, product_id)
    return jsonify(product=_product_data(product))


@bp.post("/<int:product_id>")
@bp.put("/<int:product_id>")
@bp.patch("/<int:product_id>")
@login_required
@roles_required("ADMIN", "OWNER")
def update(product_id: int):
    product = tenant_get_or_404(Product, product_id)
    data = payload()
    old_image_url = product.image_url
    pending_image: PendingImage | None = None
    try:
        pending_image = _prepare_image(replacing_url=old_image_url)
        changes = {}
        if pending_image:
            changes["image_url"] = pending_image.public_url
        for field, maximum in {
            "name": 180,
            "description": 6000,
            "sku": 80,
            "category": 100,
            "brand": 100,
            "image_url": 500,
        }.items():
            if field in data:
                if field == "image_url" and pending_image:
                    continue
                value = str(data[field]).strip()
                changes[field] = value[:maximum] or None
        if "price" in data:
            changes["price"] = _money(data["price"])
        if "promotional_price" in data:
            changes["promotional_price"] = _money(
                data["promotional_price"], optional=True
            )
        if "active" in data or "is_active" in data:
            changes["is_active"] = coerce_bool(
                data.get("active", data.get("is_active"))
            )
        product = UpdateProductService().execute(
            current_company_id(), product_id, commit=False, **changes
        )
        record_audit("product.update", product)
        db.session.commit()
    except (ValueError, IntegrityError) as exc:
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        message = str(exc) if isinstance(exc, ValueError) else "SKU ja utilizado."
        return failure(message or "Nao foi possivel atualizar; revise SKU e precos.", status=409 if isinstance(exc, IntegrityError) else 422)
    except (OSError, RuntimeError):
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        current_app.logger.exception("Falha ao preparar nova imagem do produto")
        return failure("Nao foi possivel armazenar a imagem do produto.", status=500)
    except Exception:
        if pending_image:
            pending_image.cleanup()
        db.session.rollback()
        current_app.logger.exception("Falha inesperada ao atualizar produto com imagem")
        return failure("Nao foi possivel atualizar o produto.", status=500)
    if pending_image:
        try:
            pending_image.finalize()
        except OSError:
            pending_image.cleanup()
            current_app.logger.exception("Falha ao finalizar imagem apos atualizar produto")
            product.image_url = old_image_url
            db.session.commit()
            return failure("Nao foi possivel concluir o armazenamento da imagem.", status=500)
    return success("Produto atualizado.", data=_product_data(product), endpoint="products.index")


@bp.post("/<int:product_id>/toggle")
@login_required
@roles_required("ADMIN", "OWNER")
def toggle(product_id: int):
    product = tenant_get_or_404(Product, product_id)
    product = UpdateProductService().execute(
        current_company_id(),
        product_id,
        is_active=not product.is_active,
        commit=False,
    )
    record_audit("product.toggle", product, {"is_active": product.is_active})
    db.session.commit()
    return success("Status do produto atualizado.", data={"id": product.id, "active": product.is_active})


@bp.delete("/<int:product_id>")
@bp.post("/<int:product_id>/archive")
@bp.post("/<int:product_id>/delete")
@login_required
@roles_required("ADMIN", "OWNER")
def delete(product_id: int):
    product = ArchiveProductService().execute(
        current_company_id(), product_id, commit=False
    )
    record_audit("product.archive", product)
    db.session.commit()
    return success("Produto arquivado com o historico preservado.", endpoint="products.index")


@bp.post("/<int:product_id>/variants")
@login_required
@roles_required("ADMIN", "OWNER")
def create_variant(product_id: int):
    product = tenant_get_or_404(Product, product_id)
    data = payload()
    try:
        variant = CreateProductVariantService().execute(
            current_company_id(),
            product_id,
            name=data.get("name"),
            color=data.get("color"),
            size=data.get("size"),
            sku=data.get("sku"),
            price=_money(data.get("price"), optional=True),
            is_active=coerce_bool(data.get("active", data.get("is_active")), True),
            minimum_quantity=max(0, int(data.get("minimum_quantity", 0) or 0)),
            initial_stock=int(data.get("stock", 0) or 0),
            actor_user_id=current_user.id,
            commit=False,
        )
        record_audit("product_variant.create", variant)
        db.session.commit()
    except (ValueError, DomainError, IntegrityError) as exc:
        db.session.rollback()
        message = exc.message if isinstance(exc, DomainError) else "Revise os dados e o SKU da variante."
        return failure(message, status=409 if isinstance(exc, IntegrityError) else 422)
    return success("Variante criada.", data=_product_data(product), status=201)


@bp.patch("/variants/<int:variant_id>")
@bp.post("/variants/<int:variant_id>")
@login_required
@roles_required("ADMIN", "OWNER")
def update_variant(variant_id: int):
    variant = tenant_get_or_404(ProductVariant, variant_id)
    data = payload()
    try:
        changes = {}
        for field, maximum in {"name": 180, "color": 80, "size": 80, "sku": 80}.items():
            if field in data:
                changes[field] = str(data[field]).strip()[:maximum] or None
        if "price" in data:
            changes["price"] = _money(data["price"], optional=True)
        if "active" in data or "is_active" in data:
            changes["is_active"] = coerce_bool(
                data.get("active", data.get("is_active"))
            )
        variant = UpdateProductVariantService().execute(
            current_company_id(), variant_id, commit=False, **changes
        )
        record_audit("product_variant.update", variant)
        db.session.commit()
    except (ValueError, IntegrityError):
        db.session.rollback()
        return failure("Nao foi possivel atualizar a variante.", status=409)
    return success("Variante atualizada.", data=_product_data(variant.product))


@bp.delete("/variants/<int:variant_id>")
@login_required
@roles_required("ADMIN", "OWNER")
def delete_variant(variant_id: int):
    variant = ArchiveProductVariantService().execute(
        current_company_id(), variant_id, commit=False
    )
    record_audit("product_variant.archive", variant)
    db.session.commit()
    return success("Variante arquivada.")


class ProductsController:
    """Handlers HTTP do dominio de produtos."""

    uploaded_image = staticmethod(uploaded_image)
    index = staticmethod(index)
    create = staticmethod(create)
    detail = staticmethod(detail)
    update = staticmethod(update)
    toggle = staticmethod(toggle)
    delete = staticmethod(delete)
    create_variant = staticmethod(create_variant)
    update_variant = staticmethod(update_variant)
    delete_variant = staticmethod(delete_variant)


for _endpoint, _handler in {
    "uploaded_image": ProductsController.uploaded_image,
    "index": ProductsController.index,
    "create": ProductsController.create,
    "detail": ProductsController.detail,
    "update": ProductsController.update,
    "toggle": ProductsController.toggle,
    "delete": ProductsController.delete,
    "create_variant": ProductsController.create_variant,
    "update_variant": ProductsController.update_variant,
    "delete_variant": ProductsController.delete_variant,
}.items():
    bp.view_functions[_endpoint] = _handler

del _endpoint, _handler
