import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Tạo hoặc cập nhật tài khoản Superuser dựa trên biến môi trường (ADMIN_EMAIL, ADMIN_PASSWORD)"

    def handle(self, *args, **options):
        User = get_user_model()
        email = os.environ.get("ADMIN_EMAIL")
        password = os.environ.get("ADMIN_PASSWORD")

        if not email or not password:
            self.stdout.write(
                self.style.ERROR(
                    "Thiếu ADMIN_EMAIL hoặc ADMIN_PASSWORD trong môi trường (.env)."
                )
            )
            return

        email = email.strip().lower()

        # Check if user exists by email or username
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User.objects.filter(username__iexact=email).first()

        if not user:
            User.objects.create_superuser(
                username=email, email=email, password=password
            )
            self.stdout.write(
                self.style.SUCCESS(f"Đã tạo thành công tài khoản quản trị viên: {email}")
            )
        else:
            user.is_superuser = True
            user.is_staff = True
            user.set_password(password)
            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"Đã cập nhật mật khẩu và quyền hạn cho tài khoản: {email}")
            )
