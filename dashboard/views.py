import json
import logging
import hashlib
from smtplib import SMTPException
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordResetView
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail, send_mass_mail
from django.db import models, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .forms import ApiKeyCreateForm, CustomerCreateForm, CustomerUpdateForm, DashboardPasswordResetForm, RegistrationForm, TokenPurchaseForm
from .models import CustomerAccount, ManagedApiKey, PaymentCodeLease, SePayWebhookEvent, TokenPurchase, UserApiAccess
from .payments import create_purchase_with_reserved_code, generate_vietqr_url, normalize_sepay_payload, payment_values, promotion_bonus, webhook_provided_secret, webhook_secret_is_valid
from .services import LEGACY_DELETED_KEY_REASON, RouterApiError, available_api_keys, create_router_api_key, customer_spent, delete_router_api_key, member_cost_report, reactivate_quota_disabled_keys, usage_activity_report, usage_report, usage_totals_by_api_id


logger = logging.getLogger(__name__)


class DashboardPasswordResetView(PasswordResetView):
    form_class = DashboardPasswordResetForm

    def form_valid(self, form):
        try:
            return super().form_valid(form)
        except (OSError, SMTPException):
            form.add_error(
                None,
                "Hệ thống chưa gửi được email lúc này. Vui lòng liên hệ quản trị viên để được đặt lại mật khẩu.",
            )
            return self.form_invalid(form)


def landing(request):
    return render(request, "dashboard/landing.html")


@require_GET
def integration_guide(request):
    return render(request, "dashboard/integration_guide.html")


def _send_registration_notification(user_id):
    try:
        user = get_user_model().objects.get(pk=user_id)
        registered_at = timezone.localtime(user.date_joined).strftime("%d/%m/%Y %H:%M:%S")
        send_mail(
            "[ALT] Có tài khoản Token Codex mới",
            (
                "Có khách hàng vừa đăng ký tài khoản Token Codex.\n\n"
                f"Họ tên: {user.first_name or 'Chưa cung cấp'}\n"
                f"Email: {user.email or user.username}\n"
                f"Thời gian đăng ký: {registered_at} (GMT+7)\n"
                "Hạn mức ban đầu: 0 USD."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [settings.ADMIN_NOTIFICATION_EMAIL],
            fail_silently=False,
        )
    except Exception:
        logger.exception("Không thể gửi email thông báo đăng ký user id=%s", user_id)


@login_required
def dashboard(request):
    if request.user.is_superuser:
        allowed_api_key_ids = None
        access_label = "Toàn bộ API"
    else:
        allowed_api_key_ids = list(request.user.api_accesses.values_list("external_api_key_id", flat=True))
        access_label = "API được cấp cho bạn"
    context = usage_report(request.GET, allowed_api_key_ids=allowed_api_key_ids)
    context.update(
        usage_activity_report(
            request.GET,
            allowed_api_key_ids=allowed_api_key_ids,
            page=request.GET.get("activity_page", 1),
        )
    )
    context["access_label"] = access_label
    if not request.user.is_superuser:
        account, _ = CustomerAccount.objects.get_or_create(user=request.user)
        spent = customer_spent(request.user)
        managed_api_keys = list(request.user.managed_api_keys.all())
        payment_success_order = None
        payment_invoice = request.GET.get("payment_invoice", "").strip().upper()
        if payment_invoice:
            payment_success_order = request.user.token_purchases.filter(
                invoice_code=payment_invoice,
                status="paid",
            ).first()
        context.update({
            "customer_account": account,
            "spent_total": spent,
            "remaining_credit": max(account.credit_limit - spent, 0),
            "managed_api_keys": managed_api_keys,
            "legacy_deleted_api_keys": [
                key
                for key in managed_api_keys
                if key.disabled_reason == LEGACY_DELETED_KEY_REASON
            ],
            "api_key_form": ApiKeyCreateForm(),
            "new_api_key": request.session.pop("new_api_key", None),
            "payment_success_order": payment_success_order,
        })
    return render(request, "dashboard/index.html", context)


def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        User = get_user_model()
        with transaction.atomic():
            user = User.objects.create_user(username=form.cleaned_data["email"], email=form.cleaned_data["email"], first_name=form.cleaned_data["full_name"], password=form.cleaned_data["password1"])
            CustomerAccount.objects.create(user=user)
            transaction.on_commit(lambda: _send_registration_notification(user.id))
        messages.success(request, "Đăng ký thành công. Quản trị viên sẽ cấp hạn mức cho tài khoản.")
        return redirect("login")
    return render(request, "registration/register.html", {"form": form})


@login_required
def create_api_key(request):
    if request.method != "POST" or request.user.is_superuser:
        raise PermissionDenied
    account, _ = CustomerAccount.objects.get_or_create(user=request.user)
    form = ApiKeyCreateForm(request.POST)
    eligible = account.allow_key_creation and account.credit_limit > customer_spent(request.user) and request.user.managed_api_keys.filter(is_active=True).count() < account.max_api_keys
    if not eligible:
        messages.error(request, "Tài khoản chưa đủ điều kiện tạo thêm API.")
    elif form.is_valid():
        try:
            result = create_router_api_key(f"KH{request.user.id}-{form.cleaned_data['name']}")
            raw_key = result["key"]
            ManagedApiKey.objects.create(user=request.user, external_api_key_id=result["id"], api_name=form.cleaned_data["name"], key_prefix=raw_key[:12])
            UserApiAccess.objects.create(user=request.user, external_api_key_id=result["id"], api_name=form.cleaned_data["name"])
            request.session["new_api_key"] = raw_key
            messages.success(request, "Đã tạo API. Khóa chỉ hiển thị đầy đủ một lần.")
        except (RouterApiError, KeyError):
            messages.error(request, "Không thể tạo API lúc này.")
    return redirect("dashboard")


@login_required
def delete_api_key(request, key_id):
    if request.method != "POST":
        raise PermissionDenied
    key = get_object_or_404(ManagedApiKey, pk=key_id, user=request.user, is_active=True)
    try:
        key.closed_cost = usage_totals_by_api_id([key.external_api_key_id]).get(key.external_api_key_id, 0)
        delete_router_api_key(key.external_api_key_id)
        key.is_active = False
        key.disabled_reason = "Người dùng thu hồi"
        key.save(update_fields=["is_active", "disabled_reason", "closed_cost"])
        UserApiAccess.objects.filter(user=request.user, external_api_key_id=key.external_api_key_id).delete()
        messages.success(request, "Đã thu hồi API.")
    except RouterApiError:
        messages.error(request, "Không thể thu hồi API lúc này.")
    return redirect("dashboard")


def _expire_purchase_if_needed(order):
    if order.status in {"pending", "underpaid"} and timezone.now() >= order.expires_at:
        order.status = "expired"
        order.save(update_fields=["status", "updated_at"])
    return order


def _latest_user_purchase_or_404(user, invoice_code):
    order = TokenPurchase.objects.filter(
        invoice_code=invoice_code,
        user=user,
    ).order_by("-created_at").first()
    if not order:
        raise Http404
    return order


@login_required
def token_purchase(request):
    if request.user.is_superuser:
        raise PermissionDenied
    form = TokenPurchaseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        package_usd = form.cleaned_data["package_usd"]
        promotion_code = form.cleaned_data["promotion_code"]
        amount_vnd, provider_credit = payment_values(package_usd)
        bonus_credit = Decimal("0")
        promotion = None
        if promotion_code:
            promotion = settings.TOKEN_PROMOTIONS.get(promotion_code)
            if not promotion:
                form.add_error("promotion_code", "Mã khuyến mãi không tồn tại hoặc đã hết hiệu lực.")
            elif "amount_vnd" not in promotion and not promotion.get("free_credit") and package_usd < settings.TOKEN_PROMOTION_MIN_PURCHASE_USD:
                form.add_error(
                    "promotion_code",
                    f"Mã áp dụng từ gói {settings.TOKEN_PROMOTION_MIN_PURCHASE_USD} USD.",
                )
            elif promotion["first_purchase_only"] and request.user.token_purchases.filter(status="paid").exists():
                form.add_error("promotion_code", "Mã này chỉ áp dụng cho lần mua đầu tiên.")
            elif promotion.get("max_redemptions") and request.user.token_purchases.filter(
                promotion_code=promotion_code,
                status="paid",
            ).count() >= promotion["max_redemptions"]:
                form.add_error(
                    "promotion_code",
                    f"Mã này chỉ được sử dụng tối đa {promotion['max_redemptions']} lần trên mỗi tài khoản.",
                )
            elif not promotion.get("repeatable", False) and request.user.token_purchases.filter(
                promotion_code=promotion_code,
                status="paid",
            ).exists():
                form.add_error("promotion_code", "Bạn đã sử dụng mã khuyến mãi này.")
            elif request.user.token_purchases.filter(
                promotion_code=promotion_code,
                status__in=["pending", "underpaid"],
                expires_at__gt=timezone.now(),
            ).exists():
                form.add_error("promotion_code", "Bạn đã có một đơn đang sử dụng mã này. Hãy thanh toán hoặc chờ đơn hết hạn.")
            elif "provider_multiplier" in promotion:
                provider_credit = Decimal(package_usd * promotion["provider_multiplier"])
            elif "amount_vnd" in promotion:
                package_usd = promotion.get("purchase_value_usd", 10)
                amount_vnd = promotion["amount_vnd"]
                provider_credit = promotion["credit_usd"]
            else:
                bonus_credit = promotion_bonus(provider_credit, promotion["percent"])
        if not form.errors:
            if promotion and promotion.get("free_credit"):
                now = timezone.now()
                with transaction.atomic():
                    account, _ = CustomerAccount.objects.select_for_update().get_or_create(user=request.user)
                    if request.user.token_purchases.filter(
                        promotion_code=promotion_code,
                        status="paid",
                    ).exists():
                        form.add_error("promotion_code", "Bạn đã sử dụng mã khuyến mãi này.")
                    else:
                        credit = promotion["credit_usd"]
                        credit_limit_before = account.credit_limit
                        account.credit_limit += credit
                        account.low_credit_alert_sent_at = None
                        account.low_credit_alert_credit_limit = None
                        account.save(
                            update_fields=[
                                "credit_limit",
                                "low_credit_alert_sent_at",
                                "low_credit_alert_credit_limit",
                                "updated_at",
                            ]
                        )
                        order = create_purchase_with_reserved_code(
                            user=request.user,
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
                            lambda user_id=request.user.id: reactivate_quota_disabled_keys(
                                user_id
                            ),
                            robust=True,
                        )
                if not form.errors:
                    return redirect(f"/bang-dieu-khien/?payment_invoice={order.invoice_code}")
            else:
                order = create_purchase_with_reserved_code(
                    user=request.user,
                    purchase_usd=package_usd,
                    amount_vnd=amount_vnd,
                    provider_credit_usd=provider_credit,
                    promotion_code=promotion_code,
                    promotion_bonus_usd=bonus_credit,
                    expires_at=timezone.now() + timedelta(hours=settings.TOKEN_PAYMENT_ORDER_EXPIRES_HOURS),
                )
                return redirect("token-purchase-detail", invoice_code=order.invoice_code)
    purchases = list(request.user.token_purchases.all()[:20])
    for purchase in purchases:
        _expire_purchase_if_needed(purchase)
    return render(
        request,
        "dashboard/token_purchase.html",
        {
            "form": form,
            "purchases": purchases,
            "vnd_per_usd": settings.TOKEN_PAYMENT_VND_PER_USD,
            "provider_multiplier": settings.TOKEN_PAYMENT_PROVIDER_MULTIPLIER,
            "promotions_json": json.dumps(
                {
                    code: {
                        "percent": promotion["percent"],
                        "amount_vnd": promotion.get("amount_vnd"),
                        "credit_usd": float(promotion["credit_usd"]) if promotion.get("credit_usd") is not None else None,
                        "free_credit": promotion.get("free_credit", False),
                        "provider_multiplier": promotion.get("provider_multiplier"),
                    }
                    for code, promotion in settings.TOKEN_PROMOTIONS.items()
                }
            ),
            "promotion_max_bonus": settings.TOKEN_PROMOTION_MAX_BONUS_USD,
        },
    )


@login_required
def token_purchase_detail(request, invoice_code):
    if request.user.is_superuser:
        raise PermissionDenied
    order = _latest_user_purchase_or_404(request.user, invoice_code)
    _expire_purchase_if_needed(order)
    return render(
        request,
        "dashboard/token_purchase_detail.html",
        {
            "order": order,
            "qr_url": generate_vietqr_url(order.amount_vnd, order.invoice_code),
            "bank_name": settings.TOKEN_PAYMENT_BANK_NAME,
            "account_number": settings.TOKEN_PAYMENT_ACCOUNT_NUMBER,
            "account_name": settings.TOKEN_PAYMENT_ACCOUNT_DISPLAY_NAME,
        },
    )


@login_required
@require_GET
def token_purchase_status(request, invoice_code):
    if request.user.is_superuser:
        raise PermissionDenied
    order = _latest_user_purchase_or_404(request.user, invoice_code)
    _expire_purchase_if_needed(order)
    return JsonResponse(
        {
            "status": order.status,
            "status_label": order.get_status_display(),
            "paid": order.status == "paid",
            "credit_limit_after": str(order.credit_limit_after) if order.credit_limit_after is not None else None,
        }
    )


def _send_purchase_confirmation(order_id):
    try:
        order = TokenPurchase.objects.select_related("user").get(pk=order_id)
        customer_email = order.user.email or order.user.username
        subject = f"[ALT] Đã cộng hạn mức Token Codex — {order.invoice_code}"
        customer_message = (
            f"Xin chào,\n\nThanh toán {order.amount_vnd:,} VNĐ của đơn {order.invoice_code} đã được xác nhận.\n"
            f"Tài khoản Token Codex đã được cộng thêm {order.total_credit_usd:.4f} USD hạn mức.\n"
            f"Hạn mức mới: {order.credit_limit_after:.4f} USD.\n\nTrân trọng,\nALT"
        )
        admin_message = (
            f"Đơn {order.invoice_code} của {customer_email} đã thanh toán {order.amount_vnd:,} VNĐ.\n"
            f"Đã cộng {order.total_credit_usd:.4f} USD hạn mức Token Codex. Hạn mức mới: {order.credit_limit_after:.4f} USD."
        )
        send_mass_mail(
            (
                (subject, customer_message, settings.DEFAULT_FROM_EMAIL, [customer_email]),
                (subject, admin_message, settings.DEFAULT_FROM_EMAIL, [settings.ADMIN_NOTIFICATION_EMAIL]),
            ),
            fail_silently=False,
        )
    except Exception:
        logger.exception("Không thể gửi email xác nhận đơn mua token id=%s", order_id)


@csrf_exempt
@require_POST
def sepay_webhook(request):
    if not settings.SEPAY_WEBHOOK_SECRET:
        return JsonResponse({"success": False, "error": "Webhook chưa cấu hình"}, status=503)
    if not webhook_secret_is_valid(request):
        provided_secret, auth_source = webhook_provided_secret(request)
        fingerprint = hashlib.sha256(provided_secret.encode()).hexdigest()[:12] if provided_secret else "missing"
        request_ip = request.headers.get("X-Real-IP", "").strip() or request.META.get("REMOTE_ADDR", "")
        logger.warning(
            "SePay webhook authentication failed source=%s fingerprint=%s length=%s ip=%s",
            auth_source,
            fingerprint,
            len(provided_secret),
            request_ip,
        )
        if request_ip not in settings.SEPAY_TRUSTED_IPS:
            return JsonResponse({"success": False, "error": "Unauthorized"}, status=401)
        logger.warning("SePay webhook accepted via trusted IP fallback ip=%s", request_ip)
    try:
        payload = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)

    normalized = normalize_sepay_payload(payload)
    with transaction.atomic():
        event, created = SePayWebhookEvent.objects.get_or_create(
            event_id=normalized["event_id"],
            defaults={
                "amount_vnd": normalized["amount_vnd"],
                "transfer_content": normalized["content"],
                "payload_hash": normalized["payload_hash"],
            },
        )
        if not created:
            return JsonResponse({"success": True, "duplicate": True})
        if not normalized["is_incoming"]:
            return JsonResponse({"success": True, "ignored": "not_incoming"})
        if not normalized["invoice_code"]:
            return JsonResponse({"success": True, "ignored": "invoice_not_found"})
        if len(normalized["invoice_code"]) == 7:
            lease = PaymentCodeLease.objects.select_for_update().select_related("order__user").filter(
                code=normalized["invoice_code"]
            ).first()
            order = lease.order if lease else None
            if not order or order.status not in {"pending", "underpaid"} or timezone.now() >= order.expires_at:
                return JsonResponse({"success": True, "ignored": "order_not_found"})
        else:
            order = TokenPurchase.objects.select_for_update().select_related("user").filter(
                invoice_code=normalized["invoice_code"]
            ).order_by("-created_at").first()
            if not order:
                return JsonResponse({"success": True, "ignored": "order_not_found"})
        event.order = order
        event.save(update_fields=["order"])
        if order.status == "paid":
            return JsonResponse({"success": True, "duplicate": True})
        if timezone.now() >= order.expires_at:
            order.status = "manual_review"
            order.received_amount_vnd += normalized["amount_vnd"]
            order.save(update_fields=["status", "received_amount_vnd", "updated_at"])
            return JsonResponse({"success": True, "manual_review": True})

        order.received_amount_vnd += normalized["amount_vnd"]
        order.sepay_transaction_id = normalized["transaction_id"]
        if order.received_amount_vnd < order.amount_vnd:
            order.status = "underpaid"
            order.save(update_fields=["received_amount_vnd", "sepay_transaction_id", "status", "updated_at"])
            return JsonResponse({"success": True, "underpaid": True})

        account, _ = CustomerAccount.objects.select_for_update().get_or_create(user=order.user)
        order.credit_limit_before = account.credit_limit
        account.credit_limit += order.total_credit_usd
        account.low_credit_alert_sent_at = None
        account.low_credit_alert_credit_limit = None
        account.save(update_fields=["credit_limit", "low_credit_alert_sent_at", "low_credit_alert_credit_limit", "updated_at"])
        order.credit_limit_after = account.credit_limit
        order.status = "paid"
        order.paid_at = timezone.now()
        order.credited_at = order.paid_at
        order.save(
            update_fields=[
                "received_amount_vnd",
                "sepay_transaction_id",
                "credit_limit_before",
                "credit_limit_after",
                "status",
                "paid_at",
                "credited_at",
                "updated_at",
            ]
        )
        transaction.on_commit(
            lambda user_id=order.user_id: reactivate_quota_disabled_keys(user_id),
            robust=True,
        )
        transaction.on_commit(lambda: _send_purchase_confirmation(order.id))
    return JsonResponse({"success": True, "paid": True})


def _require_superuser(request):
    if not request.user.is_superuser:
        raise PermissionDenied


def _sync_api_access(user, api_ids, api_choices):
    api_names = {item["id"]: item["name"] for item in api_choices}
    UserApiAccess.objects.filter(user=user).delete()
    UserApiAccess.objects.bulk_create([UserApiAccess(user=user, external_api_key_id=api_id, api_name=api_names.get(api_id, "API không xác định")) for api_id in api_ids])


@login_required
def user_management(request):
    _require_superuser(request)
    User = get_user_model()
    edit_user = None
    create_form = CustomerCreateForm(prefix="create")
    update_form = None
    edit_user_id = request.GET.get("edit")
    if edit_user_id:
        edit_user = get_object_or_404(User, pk=edit_user_id, is_superuser=False)
        account, _ = CustomerAccount.objects.get_or_create(user=edit_user)
        update_form = CustomerUpdateForm(user=edit_user, prefix="update", initial={"full_name": edit_user.first_name, "email": edit_user.email or edit_user.username, "is_active": edit_user.is_active, "credit_limit": account.credit_limit, "allow_key_creation": account.allow_key_creation, "max_api_keys": account.max_api_keys, "api_ids": list(edit_user.api_accesses.values_list("external_api_key_id", flat=True))})
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "create":
            create_form = CustomerCreateForm(request.POST, prefix="create")
            if create_form.is_valid():
                with transaction.atomic():
                    user = User.objects.create_user(username=create_form.cleaned_data["email"], email=create_form.cleaned_data["email"], first_name=create_form.cleaned_data["full_name"], password=create_form.cleaned_data["password1"])
                    _sync_api_access(user, create_form.cleaned_data["api_ids"], create_form.api_choices)
                    CustomerAccount.objects.create(user=user, credit_limit=create_form.cleaned_data["credit_limit"] or 0)
                messages.success(request, "Đã tạo tài khoản người dùng.")
                return redirect("user-management")
        elif action == "update":
            edit_user = get_object_or_404(User, pk=request.POST.get("user_id"), is_superuser=False)
            update_form = CustomerUpdateForm(request.POST, user=edit_user, prefix="update")
            if update_form.is_valid():
                with transaction.atomic():
                    edit_user.first_name = update_form.cleaned_data["full_name"]
                    edit_user.email = edit_user.username = update_form.cleaned_data["email"]
                    edit_user.is_active = update_form.cleaned_data["is_active"]
                    if update_form.cleaned_data["new_password"]:
                        edit_user.set_password(update_form.cleaned_data["new_password"])
                    edit_user.save()
                    _sync_api_access(edit_user, update_form.cleaned_data["api_ids"], update_form.api_choices)
                    account, _ = CustomerAccount.objects.get_or_create(user=edit_user)
                    account.credit_limit = update_form.cleaned_data["credit_limit"] or account.credit_limit
                    account.allow_key_creation = update_form.cleaned_data["allow_key_creation"]
                    account.max_api_keys = update_form.cleaned_data["max_api_keys"] or account.max_api_keys
                    account.save()
                    transaction.on_commit(
                        lambda user_id=edit_user.id: reactivate_quota_disabled_keys(
                            user_id
                        ),
                        robust=True,
                    )
                messages.success(request, "Đã cập nhật tài khoản người dùng.")
                return redirect("user-management")
        elif action == "delete":
            delete_user = get_object_or_404(
                User, pk=request.POST.get("user_id"), is_superuser=False
            )
            display_name = delete_user.first_name or delete_user.email or delete_user.username
            active_keys = list(delete_user.managed_api_keys.filter(is_active=True))
            active_key_totals = usage_totals_by_api_id(
                [key.external_api_key_id for key in active_keys]
            )
            try:
                for key in active_keys:
                    delete_router_api_key(key.external_api_key_id)
                    key.closed_cost = active_key_totals.get(
                        key.external_api_key_id, Decimal("0")
                    )
                    key.is_active = False
                    key.disabled_reason = "Quản trị viên xóa tài khoản"
                    key.disabled_at = timezone.now()
                    key.save(
                        update_fields=[
                            "closed_cost",
                            "is_active",
                            "disabled_reason",
                            "disabled_at",
                        ]
                    )
                    UserApiAccess.objects.filter(
                        user=delete_user,
                        external_api_key_id=key.external_api_key_id,
                    ).delete()
            except RouterApiError:
                messages.error(
                    request,
                    "Chưa thể xóa tài khoản vì có API tự tạo chưa thu hồi được.",
                )
                return redirect("user-management")
            delete_user.delete()
            messages.success(request, f"Đã xóa tài khoản {display_name}.")
            return redirect("user-management")
    users = list(User.objects.filter(is_superuser=False).select_related("customer_account").prefetch_related("api_accesses").order_by("-is_active", "first_name", "username"))
    assigned_api_ids = {access.external_api_key_id for user in users for access in user.api_accesses.all()}
    cost_report = member_cost_report({"period": request.GET.get("cost_period", "month"), "start": request.GET.get("cost_start", ""), "end": request.GET.get("cost_end", "")}, assigned_api_ids)
    all_time_totals = usage_totals_by_api_id(assigned_api_ids)
    closed_costs = {
        row["user_id"]: row["total"] or Decimal("0")
        for row in ManagedApiKey.objects.filter(user__in=users, is_active=False)
        .values("user_id")
        .annotate(total=models.Sum("closed_cost"))
    }
    for user in users:
        account, _ = CustomerAccount.objects.get_or_create(user=user)
        user.filtered_usage_cost = sum((cost_report["totals"].get(access.external_api_key_id, 0) for access in user.api_accesses.all()), 0)
        user.credit_limit = account.credit_limit
        user.spent_total = sum((all_time_totals.get(access.external_api_key_id, Decimal("0")) for access in user.api_accesses.all()), Decimal("0")) + closed_costs.get(user.id, Decimal("0"))
        user.remaining_credit = max(user.credit_limit - user.spent_total, Decimal("0"))
        user.over_limit = max(user.spent_total - user.credit_limit, Decimal("0"))
        user.usage_percent = min((user.spent_total / user.credit_limit * 100), Decimal("100")) if user.credit_limit > 0 else Decimal("100") if user.spent_total > 0 else Decimal("0")
        if user.credit_limit <= 0 or user.spent_total >= user.credit_limit:
            user.usage_level = "exhausted"
        elif user.usage_percent >= 90:
            user.usage_level = "danger"
        elif user.usage_percent >= 70:
            user.usage_level = "warning"
        else:
            user.usage_level = "safe"
    sort_options = {
        "usage_desc": "Sử dụng nhiều nhất",
        "period_desc": "Chi phí kỳ chọn cao nhất",
        "newest": "Đăng ký mới nhất",
        "oldest": "Đăng ký cũ nhất",
        "name_asc": "Tên A–Z",
    }
    selected_sort = request.GET.get("sort", "newest")
    if selected_sort not in sort_options:
        selected_sort = "newest"
    if selected_sort == "usage_desc":
        users.sort(key=lambda user: (user.spent_total, user.date_joined), reverse=True)
    elif selected_sort == "period_desc":
        users.sort(
            key=lambda user: (user.filtered_usage_cost, user.date_joined), reverse=True
        )
    elif selected_sort == "oldest":
        users.sort(key=lambda user: (user.date_joined, user.id))
    elif selected_sort == "name_asc":
        users.sort(
            key=lambda user: (
                (user.first_name or user.email or user.username).casefold(),
                user.id,
            )
        )
    else:
        users.sort(key=lambda user: (user.date_joined, user.id), reverse=True)
    member_search = request.GET.get("member_search", "").strip()[:150]
    if member_search:
        normalized_search = member_search.casefold()
        member_users = [
            user
            for user in users
            if normalized_search
            in " ".join(
                filter(
                    None,
                    [user.first_name, user.last_name, user.email, user.username],
                )
            ).casefold()
        ]
    else:
        member_users = users
    history_user = None
    history_report = None
    history_user_id = request.GET.get("history_user")
    if history_user_id:
        history_user = get_object_or_404(
            User, pk=history_user_id, is_superuser=False
        )
        history_api_ids = list(
            history_user.api_accesses.values_list("external_api_key_id", flat=True)
        )
        history_report = usage_activity_report(
            {"period": "all"},
            allowed_api_key_ids=history_api_ids,
            page=request.GET.get("history_page", 1),
        )
    return render(
        request,
        "dashboard/user_management.html",
        {
            "create_form": create_form,
            "update_form": update_form,
            "edit_user": edit_user,
            "users": users,
            "member_users": member_users,
            "member_search": member_search,
            "active_api_count": len(available_api_keys()),
            "cost_report": cost_report,
            "member_total_cost": sum(
                (user.filtered_usage_cost for user in member_users), Decimal("0")
            ),
            "sort_options": sort_options,
            "selected_sort": selected_sort,
            "history_user": history_user,
            "history_report": history_report,
        },
    )
