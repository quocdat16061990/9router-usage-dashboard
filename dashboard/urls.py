from django.urls import path

from .views import create_api_key, dashboard, delete_api_key, integration_guide, landing, register, sepay_webhook, token_purchase, token_purchase_detail, token_purchase_status, user_management


urlpatterns = [
    path("", landing, name="landing"),
    path("huong-dan-tich-hop/", integration_guide, name="integration-guide"),
    path("bang-dieu-khien/", dashboard, name="dashboard"),
    path("nguoi-dung/", user_management, name="user-management"),
    path("dang-ky/", register, name="register"),
    path("api/tao/", create_api_key, name="api-key-create"),
    path("api/<int:key_id>/xoa/", delete_api_key, name="api-key-delete"),
    path("mua-token/", token_purchase, name="token-purchase"),
    path("mua-token/<str:invoice_code>/", token_purchase_detail, name="token-purchase-detail"),
    path("api/thanh-toan/<str:invoice_code>/trang-thai/", token_purchase_status, name="token-purchase-status"),
    path("payment/ipn/", sepay_webhook, name="sepay-ipn"),
    path("api/sepay/webhook/", sepay_webhook, name="sepay-webhook"),
]
