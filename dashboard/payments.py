import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone


INVOICE_PATTERN = re.compile(r"\b(CDX(?:\d{4}|[A-Z0-9]{10}))\b", re.IGNORECASE)


def generate_invoice_code():
    return f"CDX{secrets.randbelow(10000):04d}"


def create_purchase_with_reserved_code(**purchase_values):
    from .models import PaymentCodeLease, TokenPurchase

    reserved_until = timezone.now() + timedelta(days=settings.PAYMENT_CODE_REUSE_DAYS)
    for _ in range(settings.PAYMENT_CODE_RESERVATION_ATTEMPTS):
        code = generate_invoice_code()
        try:
            with transaction.atomic():
                lease = PaymentCodeLease.objects.select_for_update().filter(code=code).first()
                if lease and lease.reserved_until > timezone.now():
                    continue
                if lease is None:
                    lease = PaymentCodeLease.objects.create(
                        code=code,
                        reserved_until=reserved_until,
                    )
                order = TokenPurchase.objects.create(invoice_code=code, **purchase_values)
                lease.order = order
                lease.reserved_until = reserved_until
                lease.save(update_fields=["order", "reserved_until", "updated_at"])
                return order
        except IntegrityError:
            continue
    raise RuntimeError("Không còn mã thanh toán 4 số khả dụng. Vui lòng thử lại sau.")


def payment_values(package_usd):
    amount_vnd = int(package_usd) * settings.TOKEN_PAYMENT_VND_PER_USD
    provider_credit = Decimal(int(package_usd) * settings.TOKEN_PAYMENT_PROVIDER_MULTIPLIER)
    return amount_vnd, provider_credit


def promotion_bonus(provider_credit, percentage):
    percentage_bonus = provider_credit * Decimal(percentage) / Decimal("100")
    return min(percentage_bonus, settings.TOKEN_PROMOTION_MAX_BONUS_USD)


def generate_vietqr_url(amount_vnd, content):
    return (
        "https://img.vietqr.io/image/"
        f"{quote(settings.TOKEN_PAYMENT_BANK_ID)}-{quote(settings.TOKEN_PAYMENT_ACCOUNT_NUMBER)}-compact2.png"
        f"?amount={int(amount_vnd)}&addInfo={quote(content)}"
        f"&accountName={quote(settings.TOKEN_PAYMENT_ACCOUNT_NAME)}"
    )


def webhook_provided_secret(request):
    provided = request.headers.get("X-Secret-Key", "").strip()
    source = "X-Secret-Key" if provided else ""
    if not provided:
        authorization = request.headers.get("Authorization", "").strip()
        if " " in authorization:
            scheme, value = authorization.split(" ", 1)
            if scheme.lower() in {"apikey", "bearer"}:
                provided = value.strip()
                source = f"Authorization:{scheme.lower()}"
    return provided, source or "missing"


def webhook_secret_is_valid(request):
    configured = settings.SEPAY_WEBHOOK_SECRET
    provided, _ = webhook_provided_secret(request)
    return bool(configured and provided) and hmac.compare_digest(provided, configured)


def parse_vnd_amount(value):
    try:
        return max(int(Decimal(str(value))), 0)
    except (InvalidOperation, TypeError, ValueError):
        return 0


def normalize_sepay_payload(data):
    transfer_type = str(data.get("transferType") or data.get("transfer_type") or data.get("type") or "").lower()
    amount_vnd = parse_vnd_amount(data.get("transferAmount", data.get("amount", data.get("creditAmount", 0))))
    content = str(data.get("content") or data.get("description") or data.get("transactionContent") or "")[:500]
    transaction_id = str(
        data.get("id")
        or data.get("transactionId")
        or data.get("transaction_id")
        or data.get("referenceCode")
        or data.get("reference_number")
        or ""
    )[:120]
    invoice_match = INVOICE_PATTERN.search(content.upper())
    payload_hash = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    return {
        "event_id": transaction_id or payload_hash,
        "transaction_id": transaction_id or payload_hash,
        "amount_vnd": amount_vnd,
        "content": content,
        "invoice_code": invoice_match.group(1).upper() if invoice_match else "",
        "payload_hash": payload_hash,
        "is_incoming": transfer_type in {"in", "credit", "deposit", "incoming"},
    }
