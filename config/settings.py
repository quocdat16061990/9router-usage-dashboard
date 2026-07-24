import os
from decimal import Decimal
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-development-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "DJANGO_ALLOWED_HOSTS",
        "altcp.anhlaptrinh.vn,codex.anhlaptrinh.vn,127.0.0.1,localhost",
    ).split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    "https://altcp.anhlaptrinh.vn",
    "https://codex.anhlaptrinh.vn",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 6},
    },
]

LANGUAGE_CODE = "vi"
TIME_ZONE = "Asia/Ho_Chi_Minh"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = Path(os.environ.get("DJANGO_STATIC_ROOT", "/var/www/altcp-static"))

EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "127.0.0.1")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "false").lower() == "true"
EMAIL_USE_SSL = os.environ.get("DJANGO_EMAIL_USE_SSL", "false").lower() == "true"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL", "no-reply@anhlaptrinh.vn"
)
CREDIT_ALERT_ADMIN_EMAIL = os.environ.get(
    "CREDIT_ALERT_ADMIN_EMAIL", "nguyenvannhuan90123@gmail.com"
)
TOKEN_CODEX_WEBSITE_URL = os.environ.get(
    "TOKEN_CODEX_WEBSITE_URL", "https://codex.anhlaptrinh.vn/"
)
ADMIN_NOTIFICATION_EMAIL = os.environ.get(
    "ADMIN_NOTIFICATION_EMAIL", "nhuanlaptrinh@gmail.com"
)
SEPAY_WEBHOOK_SECRET = os.environ.get("SEPAY_WEBHOOK_SECRET", "")
SEPAY_WEBHOOK_URL = os.environ.get(
    "SEPAY_WEBHOOK_URL", "https://codex.anhlaptrinh.vn/payment/ipn/"
)
SEPAY_TRUSTED_IPS = {
    ip.strip()
    for ip in os.environ.get("SEPAY_TRUSTED_IPS", "171.244.35.2,172.236.138.20").split(",")
    if ip.strip()
}
TOKEN_PAYMENT_BANK_ID = os.environ.get("TOKEN_PAYMENT_BANK_ID", "BIDV")
TOKEN_PAYMENT_BANK_NAME = os.environ.get("TOKEN_PAYMENT_BANK_NAME", "BIDV")
TOKEN_PAYMENT_ACCOUNT_NUMBER = os.environ.get("TOKEN_PAYMENT_ACCOUNT_NUMBER", "96247ANHLAPTRINH")
TOKEN_PAYMENT_ACCOUNT_NAME = os.environ.get("TOKEN_PAYMENT_ACCOUNT_NAME", "LE THI THU NHI")
TOKEN_PAYMENT_ACCOUNT_DISPLAY_NAME = os.environ.get("TOKEN_PAYMENT_ACCOUNT_DISPLAY_NAME", "Lê Thi Thu Nhi")
TOKEN_PAYMENT_VND_PER_USD = int(os.environ.get("TOKEN_PAYMENT_VND_PER_USD", "25000"))
TOKEN_PAYMENT_PROVIDER_MULTIPLIER = int(os.environ.get("TOKEN_PAYMENT_PROVIDER_MULTIPLIER", "10"))
TOKEN_PAYMENT_ORDER_EXPIRES_HOURS = int(os.environ.get("TOKEN_PAYMENT_ORDER_EXPIRES_HOURS", "24"))
PAYMENT_CODE_REUSE_DAYS = int(os.environ.get("PAYMENT_CODE_REUSE_DAYS", "30"))
PAYMENT_CODE_RESERVATION_ATTEMPTS = int(os.environ.get("PAYMENT_CODE_RESERVATION_ATTEMPTS", "100"))
TOKEN_PROMOTION_MIN_PURCHASE_USD = int(os.environ.get("TOKEN_PROMOTION_MIN_PURCHASE_USD", "10"))
TOKEN_PROMOTION_MAX_BONUS_USD = Decimal(os.environ.get("TOKEN_PROMOTION_MAX_BONUS_USD", "1000"))
TOKEN_PROMOTIONS = {
    "CHAOMUNG30": {
        "percent": int(os.environ.get("TOKEN_PROMOTION_CHAOMUNG30_PERCENT", "30")),
        "first_purchase_only": True,
    },
    "THANTHIET50": {
        "percent": int(os.environ.get("TOKEN_PROMOTION_THANTHIET50_PERCENT", "50")),
        "first_purchase_only": False,
    },
    "HOCVIENKH": {
        "percent": 0,
        "first_purchase_only": False,
        "free_credit": True,
        "credit_usd": Decimal(os.environ.get("TOKEN_PROMOTION_HOCVIENKH_CREDIT_USD", "20")),
        "purchase_value_usd": int(os.environ.get("TOKEN_PROMOTION_HOCVIENKH_PURCHASE_VALUE_USD", "2")),
    },
    "NGUOITHAN400": {
        "percent": 0,
        "first_purchase_only": False,
        "free_credit": True,
        "credit_usd": Decimal(os.environ.get("TOKEN_PROMOTION_NGUOITHAN400_CREDIT_USD", "400")),
        "purchase_value_usd": int(os.environ.get("TOKEN_PROMOTION_NGUOITHAN400_PURCHASE_VALUE_USD", "40")),
    },
    "DAMUA3000K": {
        "percent": 0,
        "first_purchase_only": False,
        "repeatable": True,
        "amount_vnd": int(os.environ.get("TOKEN_PROMOTION_DAMUA3000K_AMOUNT_VND", "3000")),
        "credit_usd": Decimal(os.environ.get("TOKEN_PROMOTION_DAMUA3000K_CREDIT_USD", "100")),
    },
    "DAMUA4000K": {
        "percent": 0,
        "first_purchase_only": False,
        "repeatable": True,
        "amount_vnd": int(os.environ.get("TOKEN_PROMOTION_DAMUA4000K_AMOUNT_VND", "4000")),
        "credit_usd": Decimal(os.environ.get("TOKEN_PROMOTION_DAMUA4000K_CREDIT_USD", "100")),
    },
    "THANTHIETX20": {
        "percent": 0,
        "first_purchase_only": False,
        "repeatable": True,
        "max_redemptions": int(os.environ.get("TOKEN_PROMOTION_THANTHIETX20_MAX_REDEMPTIONS", "3")),
        "provider_multiplier": int(os.environ.get("TOKEN_PROMOTION_THANTHIETX20_MULTIPLIER", "20")),
    },
    "THANTHIET15": {
        "percent": 0,
        "first_purchase_only": False,
        "provider_multiplier": int(os.environ.get("TOKEN_PROMOTION_THANTHIET15_MULTIPLIER", "15")),
    },
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

NINEROUTER_SQLITE_FILE = Path(
    os.environ.get("NINEROUTER_SQLITE_FILE", "/root/.9router/db/data.sqlite")
)
