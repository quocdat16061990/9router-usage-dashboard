from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

from dashboard.models import CustomerAccount, ManagedApiKey, UserApiAccess
from dashboard.services import RouterApiError, create_router_api_key, delete_router_api_key


class Command(BaseCommand):
    help = "Tạo tài khoản khách hàng Token Codex với hạn mức USD"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email đăng nhập")
        parser.add_argument("--password", default="alt123", help="Mật khẩu ban đầu")
        parser.add_argument("--credit", default="250", help="Hạn mức USD ban đầu")
        parser.add_argument("--full-name", default="", help="Tên khách hàng")
        parser.add_argument(
            "--api-name",
            default="",
            help="Tên API hiển thị; mặc định dùng tên khách hàng hoặc email",
        )
        parser.add_argument(
            "--no-create-api",
            action="store_true",
            help="Không tự tạo API key sau khi tạo tài khoản",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Chỉ kiểm tra dữ liệu, không ghi vào database",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Cập nhật mật khẩu, tên và hạn mức nếu tài khoản đã tồn tại",
        )

    def handle(self, *args, **options):
        email = options["email"].strip().lower()
        password = options["password"]
        full_name = options["full_name"].strip()
        api_name = options["api_name"].strip() or full_name or email
        create_api = not options["no_create_api"]

        try:
            validate_email(email)
        except ValidationError as error:
            raise CommandError("Email không hợp lệ.") from error

        if len(password) < 6:
            raise CommandError("Mật khẩu phải có ít nhất 6 ký tự.")

        try:
            credit = Decimal(options["credit"])
        except (InvalidOperation, TypeError) as error:
            raise CommandError("Credit phải là một số hợp lệ.") from error
        if credit < 0:
            raise CommandError("Credit không được nhỏ hơn 0.")
        credit = credit.quantize(Decimal("0.0001"))

        user_model = get_user_model()
        existing_user = user_model.objects.filter(username__iexact=email).first()
        if existing_user and not options["update_existing"]:
            raise CommandError(
                "Tài khoản đã tồn tại. Dùng --update-existing nếu thực sự muốn cập nhật."
            )

        planned_action = "cập nhật" if existing_user else "tạo"
        if options["dry_run"]:
            api_plan = " và tạo 1 API" if create_api else " và không tạo API"
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN hợp lệ: sẽ {planned_action} tài khoản {email} "
                    f"với hạn mức ${credit:.4f}{api_plan}."
                )
            )
            return

        external_api_id = None
        raw_api_key = None
        try:
            with transaction.atomic():
                if existing_user:
                    user = existing_user
                    user.username = email
                    user.email = email
                    user.first_name = full_name
                    user.is_active = True
                    user.set_password(password)
                    user.save()
                    action = "Đã cập nhật"
                else:
                    user = user_model.objects.create_user(
                        username=email,
                        email=email,
                        password=password,
                        first_name=full_name,
                        is_active=True,
                    )
                    action = "Đã tạo"

                account, _ = CustomerAccount.objects.get_or_create(user=user)
                account.credit_limit = credit
                account.save(update_fields=["credit_limit", "updated_at"])

                has_active_api = ManagedApiKey.objects.filter(user=user, is_active=True).exists()
                if create_api and not has_active_api:
                    result = create_router_api_key(f"KH{user.id}-{api_name}")
                    external_api_id = result.get("id")
                    raw_api_key = result.get("key")
                    if not external_api_id or not raw_api_key:
                        raise RouterApiError("Hệ thống ALT không trả về API key hợp lệ.")
                    ManagedApiKey.objects.create(
                        user=user,
                        external_api_key_id=external_api_id,
                        api_name=api_name,
                        key_prefix=raw_api_key[:12],
                    )
                    UserApiAccess.objects.create(
                        user=user,
                        external_api_key_id=external_api_id,
                        api_name=api_name,
                    )
        except Exception as error:
            if external_api_id:
                try:
                    delete_router_api_key(external_api_id)
                except RouterApiError:
                    self.stderr.write(
                        "Cảnh báo: không thể tự thu hồi API ngoài sau khi lưu tài khoản thất bại."
                    )
            if isinstance(error, RouterApiError):
                raise CommandError(str(error)) from error
            raise

        self.stdout.write(
            self.style.SUCCESS(f"{action} tài khoản {email} với hạn mức ${credit:.4f}.")
        )
        if raw_api_key:
            self.stdout.write(self.style.SUCCESS(f"API name: {api_name}"))
            self.stdout.write(self.style.WARNING("API key chỉ hiển thị một lần:"))
            self.stdout.write(raw_api_key)
        elif create_api:
            self.stdout.write("Tài khoản đã có API đang hoạt động nên không tạo thêm key.")
