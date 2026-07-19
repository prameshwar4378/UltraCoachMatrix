from django.urls import path

from . import views

app_name = "ucm_partner"

urlpatterns = [
    path("auth/login/", views.partner_login, name="login"),
    path("auth/refresh/", views.partner_token_refresh, name="refresh"),
    path("auth/logout/", views.partner_logout, name="logout"),
    path("auth/me/", views.partner_me, name="me"),
    path("dashboard/", views.partner_dashboard, name="dashboard"),
    path("commissions/", views.partner_commissions, name="commissions"),
    path("leads/", views.partner_leads, name="leads"),
    path("leads/<int:lead_id>/", views.partner_lead_detail, name="lead_detail"),
    path(
        "leads/<int:lead_id>/calls/",
        views.partner_lead_call_history,
        name="lead_call_history",
    ),
    path(
        "leads/<int:lead_id>/sale-claim/",
        views.partner_lead_sale_claim,
        name="lead_sale_claim",
    ),
]
