from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from dashboard.forms import DashboardAuthenticationForm, DashboardSetPasswordForm
from dashboard.views import DashboardPasswordResetView


urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "dang-nhap/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=DashboardAuthenticationForm,
        ),
        name="login",
    ),
    path("dang-xuat/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "quen-mat-khau/",
        DashboardPasswordResetView.as_view(
            template_name="dashboard/auth/password_reset_form.html",
            email_template_name="dashboard/auth/password_reset_email.txt",
            subject_template_name="dashboard/auth/password_reset_subject.txt",
            success_url="/quen-mat-khau/da-gui/",
        ),
        name="password_reset",
    ),
    path(
        "quen-mat-khau/da-gui/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="dashboard/auth/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "dat-lai-mat-khau/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="dashboard/auth/password_reset_confirm.html",
            form_class=DashboardSetPasswordForm,
            success_url="/dat-lai-mat-khau/hoan-tat/",
        ),
        name="password_reset_confirm",
    ),
    path(
        "dat-lai-mat-khau/hoan-tat/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="dashboard/auth/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("", include("dashboard.urls")),
]
