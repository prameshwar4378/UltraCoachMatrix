from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.role_home, name="dashboard"),
    path("login/", views.RoleLoginView.as_view(), name="login"),
    path("logout/", views.RoleLogoutView.as_view(), name="logout"),
    path("subscription-expired/", views.subscription_expired, name="subscription_expired"),
    path("api/auth/login/", views.api_login, name="api_login"),
    path("api/auth/logout/", views.api_logout, name="api_logout"),
    path("api/mobile/auth/login/", views.mobile_login, name="mobile_login"),
    path("api/mobile/auth/refresh/", views.mobile_token_refresh, name="mobile_token_refresh"),
    path("api/mobile/auth/logout/", views.mobile_logout, name="mobile_logout"),
    path("api/mobile/auth/me/", views.mobile_me, name="mobile_me"),
    path("api/mobile/auth/password/", views.mobile_change_password, name="mobile_change_password"),
    path("api/mobile/profile/", views.mobile_profile, name="mobile_profile"),
    path("signup/", views.signup, name="signup"),
]
