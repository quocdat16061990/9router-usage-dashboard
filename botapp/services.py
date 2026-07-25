import re
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
logger = logging.getLogger(__name__)


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_PATTERN.fullmatch(email.strip()))


def send_telegram_otp_email(to_email: str, otp_code: str) -> bool:
    try:
        # Fallback values from settings or defaults
        company_name = getattr(settings, "COMPANY_NAME", "9Router")
        support_email = getattr(settings, "EMAIL_ACCOUNT", settings.DEFAULT_FROM_EMAIL)
        
        context = {
            "purpose": "Xác thực tài khoản Telegram",
            "code": otp_code,
            "expire_minutes": 10,
            "support_email": support_email,
            "company_name": company_name,
        }
        html_content = render_to_string("otp_email.html", context)
        text_content = render_to_string("otp_email.txt", context)
        
        subject = f"[{company_name}] Mã OTP xác thực Telegram"
        if "<" in support_email:
            from_email = support_email
        else:
            from_email = f"{company_name} <{support_email}>"
        
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=from_email,
            to=[to_email.strip()],
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()
        logger.info(f"Đã gửi email OTP xác thực Telegram tới {to_email}")
        return True
    except Exception as e:
        logger.exception(f"Lỗi gửi email OTP tới {to_email}: {e}")
        return False


def apply_free_promo_to_user(user, promotion_code: str) -> tuple[bool, str]:
    from decimal import Decimal
    from django.db import transaction
    from django.utils import timezone
    from dashboard.models import CustomerAccount, TokenPurchase
    from dashboard.payments import create_purchase_with_reserved_code
    from dashboard.services import reactivate_quota_disabled_keys

    promotion_code = promotion_code.strip().upper()
    promotion = settings.TOKEN_PROMOTIONS.get(promotion_code)
    if not promotion:
        return False, "Mã khuyến mãi không tồn tại hoặc đã hết hiệu lực."
    
    if not promotion.get("free_credit"):
        return False, "Mã này yêu cầu thanh toán. Vui lòng thực hiện trên website."
        
    try:
        with transaction.atomic():
            account, _ = CustomerAccount.objects.select_for_update().get_or_create(user=user)
            if TokenPurchase.objects.filter(user=user, promotion_code=promotion_code, status="paid").exists():
                return False, "Bạn đã sử dụng mã khuyến mãi này rồi."
            
            credit = promotion["credit_usd"]
            credit_limit_before = account.credit_limit
            account.credit_limit += credit
            account.low_credit_alert_sent_at = None
            account.low_credit_alert_credit_limit = None
            account.save(update_fields=["credit_limit", "low_credit_alert_sent_at", "low_credit_alert_credit_limit", "updated_at"])
            
            now = timezone.now()
            # Note: create_purchase_with_reserved_code checks inside settings, so we import inside settings contexts
            create_purchase_with_reserved_code(
                user=user,
                purchase_usd=promotion["purchase_value_usd"],
                amount_vnd=0,
                provider_credit_usd=credit,
                promotion_code=promotion_code,
                status="paid",
                credit_limit_before=credit_limit_before,
                credit_limit_after=account.credit_limit,
                paid_at=now,
                credited_at=now,
                expires_at=now,
            )
            
            transaction.on_commit(
                lambda: reactivate_quota_disabled_keys(user.id),
                robust=True,
            )
            return True, f"Áp dụng mã thành công! Bạn được cộng thêm ${credit:.4f} vào tài khoản."
    except Exception as e:
        logger.exception(f"Lỗi khi áp dụng mã khuyến mãi {promotion_code} cho user {user.email}: {e}")
        return False, "Đã xảy ra lỗi hệ thống khi áp dụng mã khuyến mãi."


def create_api_key_for_user(user, name: str) -> tuple[bool, str, str]:
    from dashboard.models import CustomerAccount, ManagedApiKey, UserApiAccess
    from dashboard.services import customer_spent, create_router_api_key, RouterApiError
    from django.db import transaction

    account, _ = CustomerAccount.objects.get_or_create(user=user)
    active_count = user.managed_api_keys.filter(is_active=True).count()
    spent = customer_spent(user)
    
    if not account.allow_key_creation:
        return False, "Tài khoản của bạn chưa được cấp quyền tự tạo API Key.", ""
        
    if account.credit_limit <= spent:
        return False, f"Tài khoản của bạn đã hết số dư khả dụng (Đã dùng: ${spent:.4f} / Hạn mức: ${account.credit_limit:.4f}). Vui lòng nạp thêm tiền.", ""
        
    if active_count >= account.max_api_keys:
        return False, f"Tài khoản của bạn đã đạt giới hạn số lượng API Key đang hoạt động tối đa ({account.max_api_keys} keys).", ""

    try:
        with transaction.atomic():
            result = create_router_api_key(f"KH{user.id}-{name}")
            raw_key = result["key"]
            ManagedApiKey.objects.create(
                user=user,
                external_api_key_id=result["id"],
                api_name=name,
                key_prefix=raw_key[:12]
            )
            UserApiAccess.objects.create(
                user=user,
                external_api_key_id=result["id"],
                api_name=name
            )
            return True, "Tạo API Key thành công!", raw_key
    except Exception as e:
        logger.exception(f"Lỗi khi tạo API Key cho user {user.email}: {e}")
        return False, "Không thể tạo API Key lúc này do lỗi hệ thống.", ""


def delete_api_key_for_user(user, key_id: int) -> tuple[bool, str]:
    from dashboard.models import ManagedApiKey, UserApiAccess
    from dashboard.services import delete_router_api_key, usage_totals_by_api_id, RouterApiError
    from django.db import transaction
    
    try:
        with transaction.atomic():
            key = ManagedApiKey.objects.select_for_update().filter(pk=key_id, user=user, is_active=True).first()
            if not key:
                return False, "API Key không tồn tại hoặc đã bị thu hồi trước đó."
                
            key.closed_cost = usage_totals_by_api_id([key.external_api_key_id]).get(key.external_api_key_id, 0)
            
            try:
                delete_router_api_key(key.external_api_key_id)
            except RouterApiError as exc:
                if "không còn tồn tại" not in str(exc).lower():
                    raise exc
            
            key.is_active = False
            key.disabled_reason = "Người dùng thu hồi qua Telegram"
            key.save(update_fields=["is_active", "disabled_reason", "closed_cost"])
            
            UserApiAccess.objects.filter(user=user, external_api_key_id=key.external_api_key_id).delete()
            return True, f"Đã thu hồi thành công API Key '{key.api_name}'."
    except Exception as e:
        logger.exception(f"Lỗi khi thu hồi API Key {key_id} cho user {user.email}: {e}")
        return False, "Không thể thu hồi API Key lúc này do lỗi hệ thống."

