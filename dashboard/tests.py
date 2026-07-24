import sqlite3
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from .forms import DashboardSetPasswordForm, RegistrationForm
from .models import CustomerAccount, ManagedApiKey, PaymentCodeLease, TokenPurchase, UserApiAccess


class CreateCustomerAccountCommandTests(TestCase):
    @patch("dashboard.management.commands.create_customer_account.create_router_api_key")
    def test_creates_customer_with_default_password_credit_and_api(self, create_api):
        create_api.return_value = {"id": "api-id-1", "key": "token-key-once"}

        call_command("create_customer_account", email="NEW@EXAMPLE.COM")

        user = get_user_model().objects.get(username="new@example.com")
        self.assertEqual(user.email, "new@example.com")
        self.assertTrue(user.check_password("alt123"))
        self.assertEqual(user.customer_account.credit_limit, Decimal("250.0000"))
        create_api.assert_called_once_with(f"KH{user.id}-new@example.com")
        self.assertTrue(
            ManagedApiKey.objects.filter(
                user=user,
                external_api_key_id="api-id-1",
                api_name="new@example.com",
                key_prefix="token-key-on",
            ).exists()
        )
        self.assertTrue(
            UserApiAccess.objects.filter(
                user=user,
                external_api_key_id="api-id-1",
                api_name="new@example.com",
            ).exists()
        )

    def test_refuses_to_overwrite_existing_customer_by_default(self):
        get_user_model().objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="original-password",
        )

        with self.assertRaises(CommandError):
            call_command("create_customer_account", email="member@example.com")

    def test_dry_run_does_not_create_customer(self):
        call_command("create_customer_account", email="preview@example.com", dry_run=True)

        self.assertFalse(
            get_user_model().objects.filter(username="preview@example.com").exists()
        )

    @patch("dashboard.management.commands.create_customer_account.create_router_api_key")
    def test_updates_existing_customer_only_with_explicit_flag(self, create_api):
        create_api.return_value = {"id": "api-id-2", "key": "updated-token-key"}
        user = get_user_model().objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="original-password",
        )
        CustomerAccount.objects.create(user=user, credit_limit=Decimal("10"))

        call_command(
            "create_customer_account",
            email="member@example.com",
            password="new-password",
            credit="300",
            update_existing=True,
        )

        user.refresh_from_db()
        self.assertTrue(user.check_password("new-password"))
        self.assertEqual(user.customer_account.credit_limit, Decimal("300.0000"))
        self.assertTrue(ManagedApiKey.objects.filter(user=user, external_api_key_id="api-id-2").exists())

    @patch("dashboard.management.commands.create_customer_account.create_router_api_key")
    def test_no_create_api_option_skips_router_call(self, create_api):
        call_command(
            "create_customer_account",
            email="account-only@example.com",
            no_create_api=True,
        )

        create_api.assert_not_called()
        user = get_user_model().objects.get(username="account-only@example.com")
        self.assertFalse(ManagedApiKey.objects.filter(user=user).exists())
from .services import LEGACY_DELETED_KEY_REASON, QUOTA_DISABLED_REASON, RouterApiError, RouterApiNotFoundError, customer_spent, member_cost_report, usage_activity_report, usage_report, usage_totals_by_api_id


class LandingPageTests(TestCase):
    def test_landing_page_is_public_and_explains_pricing(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1 USD thanh toán")
        self.assertContains(response, "10 USD hạn mức")
        self.assertContains(response, "Tiết kiệm đến 90%")
        self.assertContains(response, "/static/img/logo-anh-lap-trinh.png")
        self.assertContains(response, "/huong-dan-tich-hop/")

    def test_integration_guide_is_public_and_contains_safe_examples(self):
        response = self.client.get("/huong-dan-tich-hop/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://codex.anhlaptrinh.vn/v1")
        self.assertContains(response, "OpenClaw")
        self.assertContains(response, "Antigravity / Codex")
        self.assertContains(response, "Hermes Agent")
        self.assertContains(response, "YOUR_TOKEN_CODEX_API_KEY")
        self.assertContains(response, "GPT-5.6-sol")
        self.assertContains(response, "GPT-5.6-sol")
        self.assertContains(response, "GPT-5.6-terra")
        self.assertContains(response, "GPT-5.6-luna")
        self.assertNotContains(response, "TEN_MODEL")
        self.assertNotContains(response, "sk-")

    def test_dashboard_requires_login_at_new_path(self):
        response = self.client.get("/bang-dieu-khien/")

        self.assertRedirects(
            response,
            "/dang-nhap/?next=/bang-dieu-khien/",
            fetch_redirect_response=False,
        )


class PasswordPolicyTests(TestCase):
    def test_registration_page_renders_new_auth_template(self):
        response = self.client.get("/dang-ky/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tạo tài khoản Token Codex")
        self.assertContains(response, "/static/img/logo-anh-lap-trinh.png")
        self.assertContains(response, 'id="register-form"')

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
        ADMIN_NOTIFICATION_EMAIL="owner@example.com",
    )
    def test_registration_sends_admin_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/dang-ky/",
                {
                    "full_name": "Khách hàng mới",
                    "email": "new-customer@example.com",
                    "password1": "123456",
                    "password2": "123456",
                },
            )

        self.assertRedirects(response, "/dang-nhap/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertIn("Khách hàng mới", mail.outbox[0].body)
        self.assertIn("new-customer@example.com", mail.outbox[0].body)
        self.assertIn("0 USD", mail.outbox[0].body)

    def registration_form(self, password):
        return RegistrationForm(
            data={
                "full_name": "Khách hàng thử",
                "email": "password-test@example.com",
                "password1": password,
                "password2": password,
            }
        )

    def test_accepts_six_numeric_characters(self):
        self.assertTrue(self.registration_form("123456").is_valid())

    def test_accepts_six_letter_characters(self):
        self.assertTrue(self.registration_form("abcdef").is_valid())

    def test_rejects_fewer_than_six_characters(self):
        form = self.registration_form("12345")

        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    def test_password_reset_accepts_six_numeric_characters(self):
        user = get_user_model().objects.create_user(
            username="reset@example.com", password="old-password"
        )
        form = DashboardSetPasswordForm(
            user,
            data={"new_password1": "123456", "new_password2": "123456"},
        )

        self.assertTrue(form.is_valid())

    def test_forgot_password_page_is_available(self):
        response = self.client.get("/quen-mat-khau/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quên mật khẩu")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_forgot_password_sends_reset_link(self):
        get_user_model().objects.create_user(
            username="member@example.com",
            email="member@example.com",
            password="old-password",
        )

        response = self.client.post(
            "/quen-mat-khau/", {"email": "member@example.com"}
        )

        self.assertRedirects(response, "/quen-mat-khau/da-gui/")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/dat-lai-mat-khau/", mail.outbox[0].body)
        self.assertIn("Token Codex", mail.outbox[0].subject)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
    )
    def test_forgot_password_reports_unregistered_email(self):
        response = self.client.post(
            "/quen-mat-khau/", {"email": "unknown@example.com"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email này chưa được đăng ký")
        self.assertEqual(len(mail.outbox), 0)


class UsageReportTests(TestCase):
    def setUp(self):
        self.temp_directory = TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.database_file = Path(self.temp_directory.name) / "data.sqlite"
        self.customer_key_value = "test-key-value"
        self.other_key_value = "other-test-key-value"
        self.customer_key_id = "11111111-1111-1111-1111-111111111111"
        self.other_key_id = "22222222-2222-2222-2222-222222222222"
        with sqlite3.connect(self.database_file) as connection:
            connection.executescript(
                """
                CREATE TABLE apiKeys (
                    id TEXT PRIMARY KEY,
                    key TEXT NOT NULL,
                    name TEXT,
                    isActive INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE usageHistory (
                    id INTEGER PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    provider TEXT,
                    model TEXT,
                    apiKey TEXT,
                    endpoint TEXT,
                    promptTokens INTEGER DEFAULT 0,
                    completionTokens INTEGER DEFAULT 0,
                    cost REAL,
                    status TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO apiKeys (id, key, name) VALUES (?, ?, ?)",
                (self.customer_key_id, self.customer_key_value, "Khách hàng A"),
            )
            connection.execute(
                "INSERT INTO apiKeys (id, key, name) VALUES (?, ?, ?)",
                (self.other_key_id, self.other_key_value, "Khách hàng B"),
            )

    def _write_usage(self, records):
        with sqlite3.connect(self.database_file) as connection:
            connection.executemany(
                """INSERT INTO usageHistory
                (timestamp, provider, model, apiKey, endpoint, promptTokens, completionTokens, cost, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        record["timestamp"],
                        record.get("provider", "codex"),
                        record.get("model", "gpt-test"),
                        record.get("apiKey"),
                        record.get("endpoint", "/v1/responses"),
                        record.get("promptTokens", 0),
                        record.get("completionTokens", 0),
                        record.get("cost"),
                        record.get("status", "ok"),
                    )
                    for record in records
                ],
            )

    @override_settings(TIME_ZONE="Asia/Ho_Chi_Minh")
    def test_groups_requests_by_api_name(self):
        now = datetime.now(datetime_timezone.utc).isoformat()
        self._write_usage(
            [
                {"apiKey": self.customer_key_value, "timestamp": now, "cost": 0.25},
                {"apiKey": self.customer_key_value, "timestamp": now, "cost": 0.75},
            ]
        )
        today = timezone.localdate().isoformat()

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report(
                {"period": "custom", "start": today, "end": today}
            )

        self.assertEqual(report["total_requests"], 2)
        self.assertEqual(str(report["total_cost"]), "1.00")
        self.assertEqual(report["rows"][0]["api_name"], "Khách hàng A")

    @override_settings(TIME_ZONE="Asia/Ho_Chi_Minh")
    def test_excludes_records_outside_range(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2020-01-01T00:00:00Z",
                    "cost": 10,
                }
            ]
        )
        today = timezone.localdate().isoformat()

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report(
                {"period": "custom", "start": today, "end": today}
            )

        self.assertEqual(report["total_requests"], 0)

    def test_all_period_includes_complete_history(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2020-01-01T00:00:00Z",
                    "cost": 2.5,
                }
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report({"period": "all"})

        self.assertEqual(report["total_requests"], 1)
        self.assertEqual(str(report["total_cost"]), "2.5")
        self.assertEqual(report["range_label"], "Toàn bộ lịch sử")

    def test_usage_totals_by_api_id_aggregates_assigned_costs(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1.25,
                },
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T01:00:00Z",
                    "cost": 2.75,
                },
                {
                    "apiKey": self.other_key_value,
                    "timestamp": "2026-07-16T02:00:00Z",
                    "cost": 9,
                },
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            totals = usage_totals_by_api_id([self.customer_key_id])

        self.assertEqual(totals[self.customer_key_id], 4)
        self.assertNotIn(self.other_key_id, totals)

    @override_settings(TIME_ZONE="Asia/Ho_Chi_Minh")
    def test_member_cost_report_filters_custom_date_range(self):
        self._write_usage(
            [
                {"apiKey": self.customer_key_value, "timestamp": "2026-07-15T00:00:00Z", "cost": 2},
                {"apiKey": self.customer_key_value, "timestamp": "2026-07-16T00:00:00Z", "cost": 5},
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = member_cost_report(
                {"period": "custom", "start": "2026-07-16", "end": "2026-07-16"},
                [self.customer_key_id],
            )

        self.assertEqual(str(report["totals"][self.customer_key_id]), "5.0")
        self.assertEqual(report["range_label"], "16/07/2026 – 16/07/2026")

    def test_unknown_api_key_is_grouped_safely(self):
        self._write_usage(
            [
                {
                    "apiKey": "removed-key",
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1,
                }
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report({"period": "all"})

        self.assertEqual(report["rows"][0]["api_name"], "API không xác định")

    def test_limits_report_to_assigned_api_ids(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1,
                },
                {
                    "apiKey": self.other_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 9,
                },
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report(
                {"period": "all"}, allowed_api_key_ids=[self.customer_key_id]
            )

        self.assertEqual(report["api_count"], 1)
        self.assertEqual(report["rows"][0]["api_name"], "Khách hàng A")
        self.assertEqual(str(report["total_cost"]), "1.0")

    def test_empty_assignment_cannot_see_any_usage(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1,
                }
            ]
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_report({"period": "all"}, allowed_api_key_ids=[])

        self.assertEqual(report["total_requests"], 0)
        self.assertEqual(report["rows"], [])

    @override_settings(TIME_ZONE="Asia/Ho_Chi_Minh")
    def test_activity_report_shows_request_time_tokens_and_cost(self):
        self._write_usage([
            {
                "apiKey": self.customer_key_value,
                "timestamp": "2026-07-17T01:02:03Z",
                "promptTokens": 120,
                "completionTokens": 30,
                "cost": 0.012345,
                "status": "ok",
            }
        ])

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_activity_report(
                {"period": "custom", "start": "2026-07-17", "end": "2026-07-17"},
                [self.customer_key_id],
            )

        row = report["activity_rows"][0]
        self.assertEqual(row["occurred_at"].strftime("%H:%M:%S"), "08:02:03")
        self.assertEqual(row["total_tokens"], 150)
        self.assertEqual(str(row["cost"]), "0.012345")
        self.assertEqual(report["activity_successful"], 1)

    def test_activity_report_cannot_show_another_customers_requests(self):
        self._write_usage([
            {"apiKey": self.customer_key_value, "timestamp": "2026-07-17T01:00:00Z", "cost": 1},
            {"apiKey": self.other_key_value, "timestamp": "2026-07-17T02:00:00Z", "cost": 9},
        ])

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            report = usage_activity_report({"period": "all"}, [self.customer_key_id])

        self.assertEqual(report["activity_total"], 1)
        self.assertEqual(report["activity_rows"][0]["api_name"], "Khách hàng A")

    def test_customer_dashboard_only_renders_assigned_api(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1,
                },
                {
                    "apiKey": self.other_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 9,
                },
            ]
        )
        user = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="test-password",
        )
        UserApiAccess.objects.create(
            user=user,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.get("/bang-dieu-khien/?period=all")

        self.assertContains(response, "Khách hàng A")
        self.assertNotContains(response, "Khách hàng B")
        self.assertContains(response, "API được cấp cho bạn")
        self.assertContains(response, "Tài khoản đang đăng nhập")
        self.assertContains(response, "customer@example.com")

    def test_superuser_dashboard_renders_all_apis(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1,
                },
                {
                    "apiKey": self.other_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 9,
                },
            ]
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.get("/bang-dieu-khien/?period=all")

        self.assertContains(response, "Khách hàng A")
        self.assertContains(response, "Khách hàng B")
        self.assertContains(response, "Toàn bộ API")

    def test_regular_user_cannot_open_user_management(self):
        user = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        self.client.force_login(user)

        response = self.client.get("/nguoi-dung/")

        self.assertEqual(response.status_code, 403)

    def test_user_management_displays_each_customers_total_cost(self):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T00:00:00Z",
                    "cost": 1.5,
                },
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-16T01:00:00Z",
                    "cost": 2.5,
                },
            ]
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.get("/nguoi-dung/")

        self.assertContains(response, "Chi phí theo thành viên")
        self.assertContains(response, "Tháng này")
        self.assertContains(response, "$4.000000")

    def test_user_management_filters_member_report_by_name_and_email(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        first_customer = get_user_model().objects.create_user(
            username="an@example.com",
            email="an@example.com",
            first_name="Nguyễn Văn An",
            password="test-password",
        )
        second_customer = get_user_model().objects.create_user(
            username="binh@example.com",
            email="binh@example.com",
            first_name="Trần Bình",
            password="test-password",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            name_response = self.client.get(
                "/nguoi-dung/", {"member_search": "văn an"}
            )
            email_response = self.client.get(
                "/nguoi-dung/", {"member_search": "binh@example"}
            )

        self.assertEqual(list(name_response.context["member_users"]), [first_customer])
        self.assertEqual(list(email_response.context["member_users"]), [second_customer])
        self.assertContains(name_response, 'value="văn an"')
        self.assertContains(
            name_response,
            "<strong>1</strong><span>kết quả phù hợp</span>",
            html=True,
        )

    def test_user_management_displays_credit_usage_and_remaining_amount(self):
        self._write_usage(
            [{"apiKey": self.customer_key_value, "timestamp": "2026-07-16T00:00:00Z", "cost": 4}]
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        CustomerAccount.objects.create(user=customer, credit_limit=10)
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.get("/nguoi-dung/")

        self.assertContains(response, "Hạn mức")
        self.assertContains(response, "Đã sử dụng")
        self.assertContains(response, "$10.0000")
        self.assertContains(response, "$4.0000")
        self.assertContains(response, "$6.0000")
        self.assertContains(response, "40.0%")

    def test_user_management_includes_closed_cost_and_marks_over_limit(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        CustomerAccount.objects.create(user=customer, credit_limit=3)
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
            is_active=False,
            closed_cost=5,
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.get("/nguoi-dung/")

        self.assertContains(response, "Vượt $2.0000")
        self.assertContains(response, "100.0%")

    def test_superuser_can_create_customer_with_api_assignment(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.post(
                "/nguoi-dung/",
                {
                    "action": "create",
                    "create-full_name": "Khách hàng thử",
                    "create-email": "new-customer@example.com",
                    "create-password1": "Strong-Test-Password-2026!",
                    "create-password2": "Strong-Test-Password-2026!",
                    "create-api_ids": [self.customer_key_id],
                },
            )

        self.assertRedirects(response, "/nguoi-dung/")
        customer = get_user_model().objects.get(
            username="new-customer@example.com"
        )
        self.assertFalse(customer.is_superuser)
        self.assertFalse(customer.is_staff)
        self.assertTrue(customer.check_password("Strong-Test-Password-2026!"))
        self.assertEqual(customer.api_accesses.count(), 1)
        self.assertEqual(
            customer.api_accesses.get().external_api_key_id,
            self.customer_key_id,
        )

    def test_superuser_can_update_customer_and_replace_assignments(self):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="old@example.com", password="old-password"
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.post(
                "/nguoi-dung/",
                {
                    "action": "update",
                    "user_id": customer.id,
                    "update-full_name": "Tên mới",
                    "update-email": "new@example.com",
                    "update-is_active": "on",
                    "update-new_password": "",
                    "update-api_ids": [self.other_key_id],
                },
            )

        self.assertRedirects(response, "/nguoi-dung/")
        customer.refresh_from_db()
        self.assertEqual(customer.username, "new@example.com")
        self.assertEqual(customer.first_name, "Tên mới")
        self.assertEqual(customer.api_accesses.count(), 1)
        self.assertEqual(
            customer.api_accesses.get().external_api_key_id,
            self.other_key_id,
        )

    @patch("dashboard.services.set_router_api_key_active")
    def test_admin_credit_update_preserves_and_reactivates_quota_key(
        self, set_key_active
    ):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            first_name="Khách hàng",
            password="test-password",
        )
        CustomerAccount.objects.create(user=customer, credit_limit=1)
        key = ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
            is_active=False,
            disabled_reason=QUOTA_DISABLED_REASON,
            disabled_at=timezone.now(),
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    "/nguoi-dung/",
                    {
                        "action": "update",
                        "user_id": customer.id,
                        "update-full_name": "Khách hàng",
                        "update-email": "customer@example.com",
                        "update-is_active": "on",
                        "update-credit_limit": "10",
                        "update-allow_key_creation": "on",
                        "update-max_api_keys": "5",
                        "update-new_password": "",
                        "update-api_ids": [self.customer_key_id],
                    },
                )

        self.assertRedirects(response, "/nguoi-dung/")
        key.refresh_from_db()
        self.assertTrue(key.is_active)
        self.assertEqual(key.disabled_reason, "")
        self.assertTrue(
            UserApiAccess.objects.filter(
                user=customer,
                external_api_key_id=self.customer_key_id,
            ).exists()
        )
        set_key_active.assert_called_once_with(self.customer_key_id, True)

    def test_user_management_sorts_by_usage_and_registration_date(self):
        self._write_usage(
            [
                {"apiKey": self.customer_key_value, "timestamp": "2026-07-16T00:00:00Z", "cost": 8},
                {"apiKey": self.other_key_value, "timestamp": "2026-07-16T00:00:00Z", "cost": 2},
            ]
        )
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        older = get_user_model().objects.create_user(
            username="older@example.com", first_name="Older", password="test-password"
        )
        newer = get_user_model().objects.create_user(
            username="newer@example.com", first_name="Newer", password="test-password"
        )
        UserApiAccess.objects.create(
            user=older,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        UserApiAccess.objects.create(
            user=newer,
            external_api_key_id=self.other_key_id,
            api_name="Khách hàng B",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            usage_response = self.client.get("/nguoi-dung/?sort=usage_desc")
            newest_response = self.client.get("/nguoi-dung/?sort=newest")

        self.assertLess(
            usage_response.content.index(b"older@example.com"),
            usage_response.content.index(b"newer@example.com"),
        )
        self.assertLess(
            newest_response.content.index(b"newer@example.com"),
            newest_response.content.index(b"older@example.com"),
        )
        self.assertContains(usage_response, "Sử dụng nhiều nhất")
        self.assertContains(newest_response, "Đăng ký mới nhất")

    @patch("dashboard.views.delete_router_api_key")
    def test_superuser_can_delete_customer_and_revoke_managed_keys(self, delete_key):
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="delete@example.com", password="test-password"
        )
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.post(
                "/nguoi-dung/", {"action": "delete", "user_id": customer.id}
            )

        self.assertRedirects(response, "/nguoi-dung/")
        delete_key.assert_called_once_with(self.customer_key_id)
        self.assertFalse(
            get_user_model().objects.filter(pk=customer.id).exists()
        )

    @patch("dashboard.views.delete_router_api_key")
    def test_delete_customer_stops_when_managed_key_cannot_be_revoked(self, delete_key):
        delete_key.side_effect = RouterApiError("router unavailable")
        admin_user = get_user_model().objects.create_superuser(
            username="admin@example.com", password="test-password"
        )
        customer = get_user_model().objects.create_user(
            username="keep@example.com", password="test-password"
        )
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        self.client.force_login(admin_user)

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            response = self.client.post(
                "/nguoi-dung/", {"action": "delete", "user_id": customer.id}
            )

        self.assertRedirects(response, "/nguoi-dung/")
        self.assertTrue(get_user_model().objects.filter(pk=customer.id).exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
        CREDIT_ALERT_ADMIN_EMAIL="admin@example.com",
        TOKEN_CODEX_WEBSITE_URL="https://codex.anhlaptrinh.vn/",
    )
    def test_credit_guard_sends_customer_and_admin_alert_once_at_eighty_percent(self):
        self._write_usage(
            [{"apiKey": self.customer_key_value, "timestamp": "2026-07-17T00:00:00Z", "cost": 8}]
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="test-password",
        )
        account = CustomerAccount.objects.create(user=customer, credit_limit=10)
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")
            call_command("enforce_credit_limits")

        account.refresh_from_db()
        self.assertIsNotNone(account.low_credit_alert_sent_at)
        self.assertEqual(account.low_credit_alert_credit_limit, account.credit_limit)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[0].to, ["customer@example.com"])
        self.assertEqual(mail.outbox[1].to, ["admin@example.com"])
        self.assertIn("Tài khoản Token Codex", mail.outbox[0].subject)
        self.assertIn("Tài khoản Token Codex", mail.outbox[0].body)
        self.assertNotIn("9Router", mail.outbox[0].subject)
        self.assertNotIn("9Router", mail.outbox[0].body)
        self.assertIn("customer@example.com", mail.outbox[1].body)
        for message in mail.outbox:
            self.assertIn("Email đăng nhập", message.body)
            self.assertIn("https://codex.anhlaptrinh.vn/", message.body)
            self.assertIn("THANTHIET15", message.body)
            self.assertIn("chỉ dùng một lần", message.body)
        self.assertNotIn("9Router", mail.outbox[1].body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
        CREDIT_ALERT_ADMIN_EMAIL="admin@example.com",
        TOKEN_CODEX_WEBSITE_URL="https://codex.anhlaptrinh.vn/",
    )
    def test_credit_guard_omits_coupon_after_customer_has_used_it(self):
        self._write_usage(
            [{"apiKey": self.customer_key_value, "timestamp": "2026-07-17T00:00:00Z", "cost": 8}]
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="test-password",
        )
        account = CustomerAccount.objects.create(user=customer, credit_limit=10)
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        TokenPurchase.objects.create(
            user=customer,
            invoice_code="CDXUSED1501",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=150,
            promotion_code="THANTHIET15",
            status="paid",
            expires_at=timezone.now(),
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")

        account.refresh_from_db()
        self.assertIsNotNone(account.low_credit_alert_sent_at)
        self.assertEqual(len(mail.outbox), 2)
        for message in mail.outbox:
            self.assertIn("Email đăng nhập", message.body)
            self.assertIn("https://codex.anhlaptrinh.vn/", message.body)
            self.assertNotIn("THANTHIET15", message.body)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
        CREDIT_ALERT_ADMIN_EMAIL="admin@example.com",
    )
    def test_credit_guard_sends_new_alert_after_credit_limit_changes(self):
        self._write_usage(
            [{"apiKey": self.customer_key_value, "timestamp": "2026-07-17T00:00:00Z", "cost": 9}]
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="test-password",
        )
        account = CustomerAccount.objects.create(user=customer, credit_limit=10)
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")
            account.credit_limit = 11
            account.save(update_fields=["credit_limit"])
            call_command("enforce_credit_limits")

        account.refresh_from_db()
        self.assertEqual(account.low_credit_alert_credit_limit, account.credit_limit)
        self.assertEqual(len(mail.outbox), 4)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="no-reply@example.com",
        CREDIT_ALERT_ADMIN_EMAIL="admin@example.com",
    )
    @patch("dashboard.management.commands.enforce_credit_limits.set_router_api_key_active")
    def test_credit_guard_soft_disables_key_without_deleting_access(
        self, set_key_active
    ):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-17T00:00:00Z",
                    "cost": 2,
                }
            ]
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com",
            email="customer@example.com",
            password="test-password",
        )
        CustomerAccount.objects.create(user=customer, credit_limit=1)
        key = ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")
            spent_after_disable = customer_spent(customer)

        key.refresh_from_db()
        self.assertFalse(key.is_active)
        self.assertEqual(key.disabled_reason, QUOTA_DISABLED_REASON)
        self.assertEqual(key.closed_cost, Decimal("0"))
        self.assertEqual(spent_after_disable, Decimal("2"))
        self.assertTrue(
            UserApiAccess.objects.filter(
                user=customer,
                external_api_key_id=self.customer_key_id,
            ).exists()
        )
        set_key_active.assert_called_once_with(self.customer_key_id, False)

    @patch("dashboard.services.set_router_api_key_active")
    def test_credit_guard_reactivates_same_key_after_limit_increases(
        self, set_key_active
    ):
        self._write_usage(
            [
                {
                    "apiKey": self.customer_key_value,
                    "timestamp": "2026-07-17T00:00:00Z",
                    "cost": 1,
                }
            ]
        )
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        CustomerAccount.objects.create(user=customer, credit_limit=10)
        key = ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
            is_active=False,
            disabled_reason=QUOTA_DISABLED_REASON,
            disabled_at=timezone.now(),
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")
            call_command("enforce_credit_limits")

        key.refresh_from_db()
        self.assertTrue(key.is_active)
        self.assertEqual(key.disabled_reason, "")
        self.assertIsNone(key.disabled_at)
        set_key_active.assert_called_once_with(self.customer_key_id, True)

    @patch("dashboard.services.set_router_api_key_active")
    def test_credit_guard_does_not_reactivate_user_revoked_key(
        self, set_key_active
    ):
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        CustomerAccount.objects.create(user=customer, credit_limit=10)
        key = ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
            is_active=False,
            disabled_reason="Người dùng thu hồi",
            disabled_at=timezone.now(),
            closed_cost=1,
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")

        key.refresh_from_db()
        self.assertFalse(key.is_active)
        self.assertEqual(key.disabled_reason, "Người dùng thu hồi")
        set_key_active.assert_not_called()

    @patch(
        "dashboard.services.set_router_api_key_active",
        side_effect=RouterApiNotFoundError("missing"),
    )
    def test_credit_guard_marks_legacy_deleted_key_for_replacement(
        self, set_key_active
    ):
        customer = get_user_model().objects.create_user(
            username="customer@example.com", password="test-password"
        )
        CustomerAccount.objects.create(user=customer, credit_limit=10)
        key = ManagedApiKey.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
            is_active=False,
            disabled_reason=QUOTA_DISABLED_REASON,
            disabled_at=timezone.now(),
            closed_cost=1,
        )
        UserApiAccess.objects.create(
            user=customer,
            external_api_key_id=self.customer_key_id,
            api_name="Khách hàng A",
        )

        with override_settings(NINEROUTER_SQLITE_FILE=self.database_file):
            call_command("enforce_credit_limits")

        key.refresh_from_db()
        self.assertFalse(key.is_active)
        self.assertEqual(key.disabled_reason, LEGACY_DELETED_KEY_REASON)
        self.assertFalse(
            UserApiAccess.objects.filter(
                user=customer,
                external_api_key_id=self.customer_key_id,
            ).exists()
        )
        set_key_active.assert_called_once_with(self.customer_key_id, True)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="no-reply@example.com",
    CREDIT_ALERT_ADMIN_EMAIL="admin@example.com",
    ADMIN_NOTIFICATION_EMAIL="owner@example.com",
    SEPAY_WEBHOOK_SECRET="test-sepay-secret",
    TOKEN_PAYMENT_VND_PER_USD=25000,
    TOKEN_PAYMENT_PROVIDER_MULTIPLIER=10,
    TOKEN_PAYMENT_ORDER_EXPIRES_HOURS=24,
    TOKEN_PROMOTION_MIN_PURCHASE_USD=10,
    TOKEN_PROMOTION_MAX_BONUS_USD=1000,
    TOKEN_PROMOTIONS={
        "CHAOMUNG30": {"percent": 30, "first_purchase_only": True},
        "THANTHIET50": {"percent": 50, "first_purchase_only": False},
        "HOCVIENKH": {
            "percent": 0,
            "first_purchase_only": False,
            "free_credit": True,
            "credit_usd": 20,
            "purchase_value_usd": 2,
        },
        "NGUOITHAN400": {
            "percent": 0,
            "first_purchase_only": False,
            "free_credit": True,
            "credit_usd": 400,
            "purchase_value_usd": 40,
        },
        "DAMUA3000K": {
            "percent": 0,
            "first_purchase_only": False,
            "repeatable": True,
            "amount_vnd": 3000,
            "credit_usd": 100,
        },
        "DAMUA4000K": {
            "percent": 0,
            "first_purchase_only": False,
            "repeatable": True,
            "amount_vnd": 4000,
            "credit_usd": 100,
        },
        "THANTHIETX20": {
            "percent": 0,
            "first_purchase_only": False,
            "repeatable": True,
            "max_redemptions": 3,
            "provider_multiplier": 20,
        },
        "THANTHIET15": {
            "percent": 0,
            "first_purchase_only": False,
            "provider_multiplier": 15,
        },
    },
)
class TokenPurchaseTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="buyer@example.com",
            email="buyer@example.com",
            password="test-password",
        )
        self.account = CustomerAccount.objects.create(user=self.user, credit_limit=25)

    def test_customer_can_create_fixed_package_order(self):
        self.client.force_login(self.user)

        response = self.client.post("/mua-token/", {"package_usd": "20"})

        order = TokenPurchase.objects.get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.purchase_usd, 20)
        self.assertEqual(order.amount_vnd, 500000)
        self.assertEqual(order.provider_credit_usd, 200)
        self.assertEqual(order.promotion_bonus_usd, 0)
        self.assertRegex(order.invoice_code, r"^CDX\d{4}$")
        self.assertEqual(
            PaymentCodeLease.objects.get(code=order.invoice_code).order,
            order,
        )

    @patch("dashboard.payments.secrets.randbelow", side_effect=[4565, 4565, 7890])
    def test_active_payment_code_collision_generates_another_code(self, _randbelow):
        self.client.force_login(self.user)

        self.client.post("/mua-token/", {"package_usd": "10"})
        self.client.post("/mua-token/", {"package_usd": "20"})

        codes = list(
            TokenPurchase.objects.filter(user=self.user)
            .order_by("created_at")
            .values_list("invoice_code", flat=True)
        )
        self.assertEqual(codes, ["CDX4565", "CDX7890"])
        self.assertEqual(PaymentCodeLease.objects.count(), 2)

    def test_first_purchase_promotion_adds_thirty_percent_bonus(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "20", "promotion_code": "chaomung30"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "CHAOMUNG30")
        self.assertEqual(order.provider_credit_usd, 200)
        self.assertEqual(order.promotion_bonus_usd, 60)
        self.assertEqual(order.total_credit_usd, 260)

    def test_promotion_bonus_is_capped_at_one_thousand_usd(self):
        self.client.force_login(self.user)

        self.client.post(
            "/mua-token/",
            {"package_usd": "1000", "promotion_code": "CHAOMUNG30"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.assertEqual(order.provider_credit_usd, 10000)
        self.assertEqual(order.promotion_bonus_usd, 1000)

    def test_loyalty_promotion_adds_fifty_percent_bonus(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXOLDPAID001",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            status="paid",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "thanthiet50"},
        )

        order = TokenPurchase.objects.exclude(status="paid").get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "THANTHIET50")
        self.assertEqual(order.provider_credit_usd, 100)
        self.assertEqual(order.promotion_bonus_usd, 50)
        self.assertEqual(order.total_credit_usd, 150)

    def test_same_promotion_cannot_be_used_twice(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXLOYALPAID1",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            promotion_code="THANTHIET50",
            promotion_bonus_usd=50,
            status="paid",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "THANTHIET50"},
        )

        self.assertContains(response, "đã sử dụng mã khuyến mãi này")
        self.assertEqual(TokenPurchase.objects.count(), 1)

    def test_special_coupon_creates_three_thousand_vnd_order_for_one_hundred_credit(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXPREVIOUS001",
            purchase_usd=20,
            amount_vnd=500000,
            provider_credit_usd=200,
            status="paid",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "500", "promotion_code": "damua3000k"},
        )

        order = TokenPurchase.objects.exclude(status="paid").get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "DAMUA3000K")
        self.assertEqual(order.purchase_usd, 10)
        self.assertEqual(order.amount_vnd, 3000)
        self.assertEqual(order.provider_credit_usd, 100)
        self.assertEqual(order.promotion_bonus_usd, 0)
        self.assertEqual(order.total_credit_usd, 100)

    def test_student_coupon_credits_twenty_usd_without_payment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "hocvienkh"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.account.refresh_from_db()
        self.assertRedirects(response, f"/bang-dieu-khien/?payment_invoice={order.invoice_code}")
        self.assertEqual(order.promotion_code, "HOCVIENKH")
        self.assertEqual(order.purchase_usd, 2)
        self.assertEqual(order.amount_vnd, 0)
        self.assertEqual(order.provider_credit_usd, 20)
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.credit_limit_before, 25)
        self.assertEqual(order.credit_limit_after, 45)
        self.assertEqual(self.account.credit_limit, 45)

    def test_student_coupon_can_only_be_used_once_per_account(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXSTUDENT001",
            purchase_usd=2,
            amount_vnd=0,
            provider_credit_usd=20,
            promotion_code="HOCVIENKH",
            status="paid",
            expires_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "HOCVIENKH"},
        )

        self.account.refresh_from_db()
        self.assertContains(response, "đã sử dụng mã khuyến mãi này")
        self.assertEqual(TokenPurchase.objects.count(), 1)
        self.assertEqual(self.account.credit_limit, 25)

    def test_family_coupon_credits_four_hundred_usd_without_payment(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "nguoithan400"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.account.refresh_from_db()
        self.assertRedirects(response, f"/bang-dieu-khien/?payment_invoice={order.invoice_code}")
        self.assertEqual(order.promotion_code, "NGUOITHAN400")
        self.assertEqual(order.purchase_usd, 40)
        self.assertEqual(order.amount_vnd, 0)
        self.assertEqual(order.provider_credit_usd, 400)
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.credit_limit_before, 25)
        self.assertEqual(order.credit_limit_after, 425)
        self.assertEqual(self.account.credit_limit, 425)

    def test_family_coupon_can_only_be_used_once_per_account(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXFAMILY4001",
            purchase_usd=40,
            amount_vnd=0,
            provider_credit_usd=400,
            promotion_code="NGUOITHAN400",
            status="paid",
            expires_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "NGUOITHAN400"},
        )

        self.account.refresh_from_db()
        self.assertContains(response, "đã sử dụng mã khuyến mãi này")
        self.assertEqual(TokenPurchase.objects.count(), 1)
        self.assertEqual(self.account.credit_limit, 25)

    def test_special_coupon_can_be_reused_after_a_paid_order(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXSPECIALPAID",
            purchase_usd=10,
            amount_vnd=3000,
            provider_credit_usd=100,
            promotion_code="DAMUA3000K",
            status="paid",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "DAMUA3000K"},
        )

        new_order = TokenPurchase.objects.exclude(status="paid").get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{new_order.invoice_code}/")
        self.assertEqual(new_order.amount_vnd, 3000)
        self.assertEqual(new_order.total_credit_usd, 100)
        self.assertEqual(TokenPurchase.objects.count(), 2)

    def test_special_coupon_webhook_credits_one_hundred_usd_once(self):
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXSPECIAL123",
            purchase_usd=10,
            amount_vnd=3000,
            provider_credit_usd=100,
            promotion_code="DAMUA3000K",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        payload = {
            "id": 3000100,
            "transferType": "in",
            "transferAmount": 3000,
            "content": f"Thanh toan {order.invoice_code}",
        }

        with self.captureOnCommitCallbacks(execute=True):
            first_response = self.client.post(
                "/payment/ipn/",
                data=payload,
                content_type="application/json",
                HTTP_X_SECRET_KEY="test-sepay-secret",
            )
        second_response = self.client.post(
            "/payment/ipn/",
            data=payload,
            content_type="application/json",
            HTTP_X_SECRET_KEY="test-sepay-secret",
        )

        self.account.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(second_response.json()["duplicate"])
        self.assertEqual(self.account.credit_limit, 125)
        self.assertEqual(order.credit_limit_after, 125)

    def test_four_thousand_coupon_creates_order_for_one_hundred_credit(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "1000", "promotion_code": "damua4000k"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "DAMUA4000K")
        self.assertEqual(order.purchase_usd, 10)
        self.assertEqual(order.amount_vnd, 4000)
        self.assertEqual(order.provider_credit_usd, 100)
        self.assertEqual(order.promotion_bonus_usd, 0)
        self.assertEqual(order.total_credit_usd, 100)

    def test_loyalty_x20_coupon_doubles_credit_multiplier_for_every_package(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "20", "promotion_code": "thanthietx20"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "THANTHIETX20")
        self.assertEqual(order.purchase_usd, 20)
        self.assertEqual(order.amount_vnd, 500000)
        self.assertEqual(order.provider_credit_usd, 400)
        self.assertEqual(order.promotion_bonus_usd, 0)
        self.assertEqual(order.total_credit_usd, 400)

    def test_loyalty_x15_coupon_multiplies_credit_for_one_purchase(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "20", "promotion_code": "thanthiet15"},
        )

        order = TokenPurchase.objects.get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{order.invoice_code}/")
        self.assertEqual(order.promotion_code, "THANTHIET15")
        self.assertEqual(order.purchase_usd, 20)
        self.assertEqual(order.amount_vnd, 500000)
        self.assertEqual(order.provider_credit_usd, 300)
        self.assertEqual(order.total_credit_usd, 300)

    def test_loyalty_x15_coupon_cannot_be_reused(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXLOYAL1501",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=150,
            promotion_code="THANTHIET15",
            status="paid",
            expires_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "20", "promotion_code": "THANTHIET15"},
        )

        self.assertContains(response, "đã sử dụng mã khuyến mãi này")
        self.assertEqual(TokenPurchase.objects.count(), 1)

    def test_loyalty_x20_coupon_can_be_reused_after_paid_order(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXLOYALX2001",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=200,
            promotion_code="THANTHIETX20",
            status="paid",
            expires_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "100", "promotion_code": "THANTHIETX20"},
        )

        new_order = TokenPurchase.objects.exclude(status="paid").get(user=self.user)
        self.assertRedirects(response, f"/mua-token/{new_order.invoice_code}/")
        self.assertEqual(new_order.purchase_usd, 100)
        self.assertEqual(new_order.amount_vnd, 2500000)
        self.assertEqual(new_order.provider_credit_usd, 2000)

    def test_loyalty_x20_coupon_rejects_fourth_paid_redemption(self):
        for index in range(3):
            TokenPurchase.objects.create(
                user=self.user,
                invoice_code=f"CDXX20PAID0{index}",
                purchase_usd=20,
                amount_vnd=500000,
                provider_credit_usd=400,
                promotion_code="THANTHIETX20",
                status="paid",
                expires_at=timezone.now(),
            )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "20", "promotion_code": "THANTHIETX20"},
        )

        self.assertContains(response, "chỉ được sử dụng tối đa 3 lần")
        self.assertEqual(TokenPurchase.objects.count(), 3)

    def test_invalid_promotion_code_does_not_create_order(self):
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "KHONGHOPLE"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mã khuyến mãi không tồn tại")
        self.assertEqual(TokenPurchase.objects.count(), 0)

    def test_promotion_is_rejected_after_a_paid_purchase(self):
        TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXPAIDORDER1",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            status="paid",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            "/mua-token/",
            {"package_usd": "10", "promotion_code": "CHAOMUNG30"},
        )

        self.assertContains(response, "chỉ áp dụng cho lần mua đầu tiên")
        self.assertEqual(TokenPurchase.objects.count(), 1)

    def test_customer_cannot_create_non_package_amount(self):
        self.client.force_login(self.user)

        response = self.client.post("/mua-token/", {"package_usd": "15"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(TokenPurchase.objects.count(), 0)

    def test_webhook_rejects_invalid_secret(self):
        with self.assertLogs("dashboard.views", level="WARNING") as captured_logs:
            response = self.client.post(
                "/payment/ipn/",
                data={"id": 1, "transferType": "in", "transferAmount": 250000, "content": "CDXABCDEFGHIJ"},
                content_type="application/json",
                HTTP_X_SECRET_KEY="wrong-secret",
            )

        self.assertEqual(response.status_code, 401)
        self.assertIn("source=X-Secret-Key", captured_logs.output[0])
        self.assertIn("length=12", captured_logs.output[0])
        self.assertNotIn("wrong-secret", captured_logs.output[0])

    def test_webhook_accepts_trusted_sepay_ip_before_payload_validation(self):
        with self.assertLogs("dashboard.views", level="WARNING") as captured_logs:
            response = self.client.post(
                "/payment/ipn/",
                data="{",
                content_type="application/json",
                HTTP_X_SECRET_KEY="wrong-secret",
                HTTP_X_REAL_IP="171.244.35.2",
            )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(any("trusted IP fallback" in line for line in captured_logs.output))

    def test_paid_webhook_credits_limit_once(self):
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXABCDEFGHIJ",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        payload = {
            "id": 987654,
            "transferType": "in",
            "transferAmount": 250000,
            "content": f"Thanh toan {order.invoice_code}",
        }

        with self.captureOnCommitCallbacks(execute=True):
            first_response = self.client.post(
                "/payment/ipn/",
                data=payload,
                content_type="application/json",
                HTTP_X_SECRET_KEY="test-sepay-secret",
            )
        second_response = self.client.post(
            "/payment/ipn/",
            data=payload,
            content_type="application/json",
            HTTP_X_SECRET_KEY="test-sepay-secret",
        )

        self.account.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertTrue(second_response.json()["duplicate"])
        self.assertEqual(self.account.credit_limit, 125)
        self.assertEqual(order.status, "paid")
        self.assertEqual(order.credit_limit_before, 25)
        self.assertEqual(order.credit_limit_after, 125)
        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(mail.outbox[1].to, ["owner@example.com"])

    @patch("dashboard.services.customer_spent", return_value=Decimal("25"))
    @patch("dashboard.services.set_router_api_key_active")
    def test_paid_webhook_immediately_reactivates_quota_disabled_key(
        self, set_key_active, customer_spent_mock
    ):
        key = ManagedApiKey.objects.create(
            user=self.user,
            external_api_key_id="quota-key-id",
            api_name="API chính",
            is_active=False,
            disabled_reason=QUOTA_DISABLED_REASON,
            disabled_at=timezone.now(),
        )
        UserApiAccess.objects.create(
            user=self.user,
            external_api_key_id="quota-key-id",
            api_name="API chính",
        )
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXREACTIVE01",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        payload = {
            "id": 987655,
            "transferType": "in",
            "transferAmount": 250000,
            "content": f"Thanh toan {order.invoice_code}",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/payment/ipn/",
                data=payload,
                content_type="application/json",
                HTTP_X_SECRET_KEY="test-sepay-secret",
            )

        key.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(key.is_active)
        self.assertEqual(key.disabled_reason, "")
        set_key_active.assert_called_once_with("quota-key-id", True)
        customer_spent_mock.assert_called()

    def test_paid_webhook_credits_base_and_promotion_bonus(self):
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXPROMO12345",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            promotion_code="CHAOMUNG30",
            promotion_bonus_usd=30,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        payload = {
            "id": 456789,
            "transferType": "in",
            "transferAmount": 250000,
            "content": f"Thanh toan {order.invoice_code}",
        }

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/payment/ipn/",
                data=payload,
                content_type="application/json",
                HTTP_X_SECRET_KEY="test-sepay-secret",
            )

        self.account.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.account.credit_limit, 155)
        self.assertEqual(order.credit_limit_before, 25)
        self.assertEqual(order.credit_limit_after, 155)
        self.assertEqual(order.total_credit_usd, 130)
        self.assertIn("130.0000 USD", mail.outbox[0].body)

    def test_paid_purchase_page_redirects_to_codex_dashboard(self):
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXREDIRECT12",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.client.force_login(self.user)

        response = self.client.get(f"/mua-token/{order.invoice_code}/")

        self.assertContains(response, "https://codex.anhlaptrinh.vn/bang-dieu-khien/")
        self.assertContains(response, "payment_invoice")

    def test_dashboard_shows_verified_paid_purchase_credit(self):
        order = TokenPurchase.objects.create(
            user=self.user,
            invoice_code="CDXPAIDVIEW1",
            purchase_usd=10,
            amount_vnd=250000,
            provider_credit_usd=100,
            status="paid",
            credit_limit_after=125,
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self.account.credit_limit = 125
        self.account.save(update_fields=["credit_limit"])
        self.client.force_login(self.user)

        response = self.client.get("/bang-dieu-khien/", {"payment_invoice": order.invoice_code})

        self.assertContains(response, "Thanh toán thành công")
        self.assertContains(response, "<strong>100 USD</strong>", html=True)
        self.assertContains(response, "125,0000 USD")

    def test_legacy_webhook_alias_remains_available(self):
        response = self.client.post(
            "/api/sepay/webhook/",
            data={"id": "alias-check"},
            content_type="application/json",
            HTTP_X_SECRET_KEY="wrong-secret",
        )

        self.assertEqual(response.status_code, 401)
