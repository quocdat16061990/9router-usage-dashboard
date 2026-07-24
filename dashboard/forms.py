import logging

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import ManagedApiKey
from .services import QUOTA_DISABLED_REASON, available_api_keys


logger = logging.getLogger(__name__)


class DashboardAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email đăng nhập",
        widget=forms.TextInput(
            attrs={
                "autocomplete": "username",
                "autofocus": True,
                "placeholder": "Nhập email tài khoản",
            }
        ),
    )
    password = forms.CharField(
        label="Mật khẩu",
        strip=False,
        widget=forms.PasswordInput(
            attrs={
                "autocomplete": "current-password",
                "placeholder": "Nhập mật khẩu",
            }
        ),
    )


class DashboardSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="Mật khẩu mới",
        strip=False,
        help_text="Tối thiểu 6 ký tự; có thể dùng chữ, số hoặc toàn số.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label="Nhập lại mật khẩu mới",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class DashboardPasswordResetForm(PasswordResetForm):
    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not any(self.get_users(email)):
            raise ValidationError(
                "Email này chưa được đăng ký hoặc tài khoản đang bị khóa. Vui lòng kiểm tra lại email đăng nhập."
            )
        return email

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        super().send_mail(
            subject_template_name,
            email_template_name,
            context,
            from_email,
            to_email,
            html_email_template_name,
        )
        local_part, _, domain = to_email.partition("@")
        masked_email = f"{local_part[:2]}***@{domain}" if domain else "email-khong-hop-le"
        logger.info("Đã gửi email đặt lại mật khẩu tới %s", masked_email)


class ApiAccessFormMixin:
    def _set_api_choices(self):
        self.api_choices = available_api_keys()
        user = getattr(self, "user", None)
        if user is not None:
            known_ids = {item["id"] for item in self.api_choices}
            for key in ManagedApiKey.objects.filter(
                user=user,
                is_active=False,
                disabled_reason=QUOTA_DISABLED_REASON,
            ):
                if key.external_api_key_id not in known_ids:
                    self.api_choices.append(
                        {"id": key.external_api_key_id, "name": key.api_name}
                    )
        self.fields["api_ids"].choices = [
            (item["id"], item["name"]) for item in self.api_choices
        ]


class CustomerCreateForm(ApiAccessFormMixin, forms.Form):
    credit_limit = forms.DecimalField(label="Hạn mức USD", min_value=0, decimal_places=4, initial=300, required=False)
    api_ids = forms.MultipleChoiceField(
        label="API được phép xem",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Có thể chọn một hoặc nhiều API.",
    )
    full_name = forms.CharField(
        label="Tên người dùng",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Ví dụ: Nguyễn Văn An"}),
    )
    email = forms.EmailField(
        label="Email đăng nhập",
        widget=forms.EmailInput(attrs={"placeholder": "email@example.com"}),
    )
    password1 = forms.CharField(
        label="Mật khẩu",
        strip=False,
        help_text="Tối thiểu 6 ký tự; có thể dùng chữ, số hoặc toàn số.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Nhập lại mật khẩu",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._set_api_choices()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Email này đã có tài khoản.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password1")
        if password and password != cleaned_data.get("password2"):
            self.add_error("password2", "Mật khẩu nhập lại chưa khớp.")
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data


class CustomerUpdateForm(ApiAccessFormMixin, forms.Form):
    credit_limit = forms.DecimalField(label="Hạn mức USD", min_value=0, decimal_places=4, required=False)
    allow_key_creation = forms.BooleanField(label="Cho phép tự tạo API", required=False)
    max_api_keys = forms.IntegerField(label="Số API tối đa", min_value=1, max_value=50, required=False)
    api_ids = forms.MultipleChoiceField(
        label="API được phép xem",
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Có thể chọn một hoặc nhiều API.",
    )
    full_name = forms.CharField(label="Tên người dùng", max_length=150)
    email = forms.EmailField(label="Email đăng nhập")
    is_active = forms.BooleanField(label="Tài khoản đang hoạt động", required=False)
    new_password = forms.CharField(
        label="Mật khẩu mới",
        required=False,
        strip=False,
        help_text="Để trống nếu không đổi; mật khẩu mới tối thiểu 6 ký tự.",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self._set_api_choices()

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if (
            get_user_model()
            .objects.filter(username__iexact=email)
            .exclude(pk=self.user.pk)
            .exists()
        ):
            raise forms.ValidationError("Email này đã thuộc tài khoản khác.")
        return email

    def clean_new_password(self):
        password = self.cleaned_data["new_password"]
        if password:
            validate_password(password, user=self.user)
        return password


class RegistrationForm(forms.Form):
    full_name = forms.CharField(label="Họ và tên", max_length=150)
    email = forms.EmailField(label="Email đăng nhập")
    password1 = forms.CharField(
        label="Mật khẩu",
        strip=False,
        help_text="Tối thiểu 6 ký tự; có thể dùng chữ, số hoặc toàn số.",
        widget=forms.PasswordInput,
    )
    password2 = forms.CharField(label="Nhập lại mật khẩu", strip=False, widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if get_user_model().objects.filter(username__iexact=email).exists():
            raise forms.ValidationError("Email này đã có tài khoản.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password1")
        if password and password != cleaned_data.get("password2"):
            self.add_error("password2", "Mật khẩu nhập lại chưa khớp.")
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("password1", error)
        return cleaned_data


class ApiKeyCreateForm(forms.Form):
    name = forms.CharField(label="Tên API", max_length=120)


class TokenPurchaseForm(forms.Form):
    package_usd = forms.TypedChoiceField(
        label="Gói thanh toán",
        choices=[(amount, f"{amount} USD") for amount in range(10, 1001, 10)],
        coerce=int,
    )
    promotion_code = forms.CharField(
        label="Mã khuyến mãi",
        max_length=40,
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Nhập mã của bạn",
                "autocomplete": "off",
            }
        ),
    )

    def clean_promotion_code(self):
        return self.cleaned_data["promotion_code"].strip().upper()
