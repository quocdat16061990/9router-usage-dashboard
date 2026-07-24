from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mass_mail
from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard.models import CustomerAccount, ManagedApiKey
from dashboard.services import (
    QUOTA_DISABLED_REASON,
    RouterApiError,
    customer_spent,
    reactivate_quota_disabled_keys,
    set_router_api_key_active,
)


class Command(BaseCommand):
    help = "Cảnh báo hạn mức, tạm khóa API khi hết và mở lại sau khi nạp thêm"

    alert_threshold = Decimal("0.80")

    def send_low_credit_alert(self, account, spent):
        customer_email = account.user.email or account.user.username
        admin_email = settings.CREDIT_ALERT_ADMIN_EMAIL
        usage_percent = spent / account.credit_limit * Decimal("100")
        subject = "[ALT] Tài khoản Token Codex sắp hết hạn mức"
        has_used_loyalty_coupon = account.user.token_purchases.filter(
            promotion_code="THANTHIET15",
            status="paid",
        ).exists()
        customer_coupon_message = ""
        admin_coupon_message = ""
        if not has_used_loyalty_coupon:
            customer_coupon_message = (
                "\n\nMã khuyến mãi tặng bạn: THANTHIET15\n"
                "Mã này chỉ dùng một lần cho mỗi tài khoản. Khi mua thêm, nhập mã để nhận "
                "hạn mức theo hệ số x15."
            )
            admin_coupon_message = (
                "\n\nMã khuyến mãi tặng khách hàng: THANTHIET15\n"
                "Mã này chỉ dùng một lần cho mỗi tài khoản và áp dụng khi mua thêm Token Codex "
                "để nhận hạn mức theo hệ số x15."
            )
        customer_message = (
            f"Xin chào,\n\n"
            f"Tài khoản Token Codex {customer_email} đã sử dụng {usage_percent:.1f}% hạn mức "
            f"(${spent:.4f} / ${account.credit_limit:.4f}).\n"
            "Tài khoản Token Codex của bạn sắp hết hạn mức. "
            "Vui lòng liên hệ admin để nạp thêm token mới.\n\n"
            f"Email đăng nhập: {customer_email}\n"
            f"Website: {settings.TOKEN_CODEX_WEBSITE_URL}"
            f"{customer_coupon_message}\n\n"
            "Trân trọng,\nALT"
        )
        admin_message = (
            f"Tài khoản Token Codex, email: {customer_email}, đã sử dụng "
            f"{usage_percent:.1f}% hạn mức "
            f"(${spent:.4f} / ${account.credit_limit:.4f}) và sắp hết.\n"
            "Vui lòng liên hệ khách hàng để nạp thêm token mới.\n\n"
            f"Email đăng nhập khách hàng: {customer_email}\n"
            f"Website: {settings.TOKEN_CODEX_WEBSITE_URL}"
            f"{admin_coupon_message}"
        )
        send_mass_mail(
            (
                (subject, customer_message, settings.DEFAULT_FROM_EMAIL, [customer_email]),
                (subject, admin_message, settings.DEFAULT_FROM_EMAIL, [admin_email]),
            ),
            fail_silently=False,
        )

    def alert_if_needed(self, account, spent):
        if account.credit_limit <= 0:
            return
        usage_ratio = spent / account.credit_limit
        if usage_ratio < self.alert_threshold:
            if account.low_credit_alert_sent_at is not None:
                account.low_credit_alert_sent_at = None
                account.low_credit_alert_credit_limit = None
                account.save(
                    update_fields=[
                        "low_credit_alert_sent_at",
                        "low_credit_alert_credit_limit",
                    ]
                )
            return
        if account.low_credit_alert_credit_limit == account.credit_limit:
            return
        try:
            self.send_low_credit_alert(account, spent)
        except Exception as error:
            self.stderr.write(
                f"Không thể gửi cảnh báo hạn mức cho user id={account.user_id}: "
                f"{error.__class__.__name__}"
            )
            return
        account.low_credit_alert_sent_at = timezone.now()
        account.low_credit_alert_credit_limit = account.credit_limit
        account.save(
            update_fields=[
                "low_credit_alert_sent_at",
                "low_credit_alert_credit_limit",
            ]
        )

    def handle(self, *args, **options):
        disabled = 0
        reactivated = 0
        missing = 0
        for account in CustomerAccount.objects.select_related("user"):
            spent = customer_spent(account.user)
            self.alert_if_needed(account, spent)
            if spent < account.credit_limit:
                recovery = reactivate_quota_disabled_keys(account.user_id)
                reactivated += recovery["reactivated"]
                missing += recovery["missing"]
                continue
            active_keys = list(
                ManagedApiKey.objects.filter(user=account.user, is_active=True)
            )
            for key in active_keys:
                try:
                    set_router_api_key_active(key.external_api_key_id, False)
                except RouterApiError as error:
                    self.stderr.write(f"Không thể khóa API id={key.id}: {error}")
                    continue
                key.is_active = False
                key.disabled_reason = QUOTA_DISABLED_REASON
                key.disabled_at = timezone.now()
                key.closed_cost = Decimal("0")
                key.save(update_fields=["is_active", "disabled_reason", "disabled_at", "closed_cost"])
                disabled += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Đã tạm khóa {disabled} API, mở lại {reactivated} API, "
                f"phát hiện {missing} key legacy đã bị xóa."
            )
        )
