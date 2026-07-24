from django import forms
from django.contrib import admin
from django.utils.html import format_html

from .models import CustomerAccount, ManagedApiKey, SePayWebhookEvent, TokenPurchase, UserApiAccess
from .services import available_api_keys, customer_spent


class UserApiAccessAdminForm(forms.ModelForm):
    external_api_key_id = forms.ChoiceField(
        label="API ALT",
        help_text="Chỉ lưu ID nội bộ và tên API, không lưu chuỗi API key.",
    )

    class Meta:
        model = UserApiAccess
        fields = ("user", "external_api_key_id")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(item["id"], item["name"]) for item in available_api_keys()]
        self.fields["external_api_key_id"].choices = choices

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected_id = self.cleaned_data["external_api_key_id"]
        names = {item["id"]: item["name"] for item in available_api_keys()}
        instance.api_name = names.get(selected_id, "API không xác định")
        if commit:
            instance.save()
        return instance


@admin.register(UserApiAccess)
class UserApiAccessAdmin(admin.ModelAdmin):
    form = UserApiAccessAdminForm
    list_display = ("user", "api_name", "external_api_key_id", "created_at")
    list_filter = ("api_name",)
    search_fields = ("user__username", "user__email", "api_name")
    autocomplete_fields = ("user",)


@admin.register(CustomerAccount)
class CustomerAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "credit_limit", "spent_amount", "remaining_amount", "allow_key_creation", "max_api_keys", "updated_at")
    list_editable = ("credit_limit", "allow_key_creation", "max_api_keys")
    search_fields = ("user__username", "user__email", "user__first_name")
    autocomplete_fields = ("user",)
    readonly_fields = ("spent_amount", "remaining_amount", "created_at", "updated_at")

    @admin.display(description="Đã sử dụng (USD)")
    def spent_amount(self, obj):
        return f"${customer_spent(obj.user):.4f}"

    @admin.display(description="Còn lại (USD)")
    def remaining_amount(self, obj):
        spent = customer_spent(obj.user)
        remaining = max(obj.credit_limit - spent, 0)
        color = "#b42318" if spent >= obj.credit_limit else "#067647"
        return format_html('<strong style="color:{}">{}</strong>', color, f"${remaining:.4f}")


admin.site.register(ManagedApiKey)


@admin.register(TokenPurchase)
class TokenPurchaseAdmin(admin.ModelAdmin):
    list_display = ("invoice_code", "user", "purchase_usd", "amount_vnd", "provider_credit_usd", "promotion_code", "promotion_bonus_usd", "status", "created_at", "paid_at")
    list_filter = ("status", "promotion_code", "created_at")
    search_fields = ("invoice_code", "user__username", "sepay_transaction_id")
    readonly_fields = ("invoice_code", "sepay_transaction_id", "credit_limit_before", "credit_limit_after", "paid_at", "credited_at", "created_at", "updated_at")


@admin.register(SePayWebhookEvent)
class SePayWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "order", "amount_vnd", "processed_at")
    search_fields = ("event_id", "order__invoice_code", "transfer_content")
    readonly_fields = ("event_id", "order", "amount_vnd", "transfer_content", "payload_hash", "processed_at")
