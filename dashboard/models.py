from django.conf import settings
from django.db import models
from decimal import Decimal


class UserApiAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_accesses",
        verbose_name="Người dùng",
    )
    external_api_key_id = models.CharField(max_length=64, verbose_name="API ALT")
    api_name = models.CharField(max_length=255, verbose_name="Tên API")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username", "api_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "external_api_key_id"],
                name="unique_user_external_api_key",
            )
        ]
        verbose_name = "Phân quyền API"
        verbose_name_plural = "Phân quyền API"

    def __str__(self):
        return f"{self.user} — {self.api_name}"


class CustomerAccount(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="customer_account")
    credit_limit = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"), verbose_name="Hạn mức USD")
    allow_key_creation = models.BooleanField(default=True, verbose_name="Cho phép tự tạo API")
    max_api_keys = models.PositiveSmallIntegerField(default=5, verbose_name="Số API tối đa")
    low_credit_alert_sent_at = models.DateTimeField(null=True, blank=True)
    low_credit_alert_credit_limit = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    telegram_chat_id = models.BigIntegerField(unique=True, null=True, blank=True, verbose_name="Telegram Chat ID")
    telegram_otp = models.CharField(max_length=6, null=True, blank=True, verbose_name="Mã OTP Telegram")
    telegram_otp_created_at = models.DateTimeField(null=True, blank=True, verbose_name="Thời gian tạo OTP Telegram")
    is_verified_telegram = models.BooleanField(default=False, verbose_name="Đã xác thực Telegram")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} — ${self.credit_limit}"


class ManagedApiKey(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="managed_api_keys")
    external_api_key_id = models.CharField(max_length=64, unique=True)
    api_name = models.CharField(max_length=255)
    key_prefix = models.CharField(max_length=24, blank=True)
    is_active = models.BooleanField(default=True)
    disabled_reason = models.CharField(max_length=255, blank=True)
    closed_cost = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("0"))
    created_at = models.DateTimeField(auto_now_add=True)
    disabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} — {self.api_name}"


class TokenPurchase(models.Model):
    STATUS_CHOICES = [
        ("pending", "Chờ thanh toán"),
        ("paid", "Đã thanh toán"),
        ("underpaid", "Thanh toán thiếu"),
        ("manual_review", "Cần kiểm tra thủ công"),
        ("expired", "Đã hết hạn"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="token_purchases")
    invoice_code = models.CharField(max_length=24, db_index=True)
    purchase_usd = models.PositiveSmallIntegerField()
    amount_vnd = models.PositiveBigIntegerField()
    provider_credit_usd = models.DecimalField(max_digits=12, decimal_places=4)
    promotion_code = models.CharField(max_length=40, blank=True, db_index=True)
    promotion_bonus_usd = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending", db_index=True)
    received_amount_vnd = models.PositiveBigIntegerField(default=0)
    sepay_transaction_id = models.CharField(max_length=120, blank=True, null=True, unique=True)
    credit_limit_before = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    credit_limit_after = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    credited_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.invoice_code} — {self.user} — {self.get_status_display()}"

    @property
    def total_credit_usd(self):
        return self.provider_credit_usd + self.promotion_bonus_usd


class PaymentCodeLease(models.Model):
    code = models.CharField(max_length=7, unique=True, db_index=True)
    order = models.OneToOneField(
        TokenPurchase,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_code_lease",
    )
    reserved_until = models.DateTimeField(db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} — giữ đến {self.reserved_until}"


class SePayWebhookEvent(models.Model):
    event_id = models.CharField(max_length=160, unique=True, db_index=True)
    order = models.ForeignKey(TokenPurchase, on_delete=models.SET_NULL, null=True, blank=True, related_name="webhook_events")
    amount_vnd = models.PositiveBigIntegerField(default=0)
    transfer_content = models.CharField(max_length=500, blank=True)
    payload_hash = models.CharField(max_length=64)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-processed_at"]

    def __str__(self):
        return self.event_id
