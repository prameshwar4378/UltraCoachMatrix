from django.urls import path

from . import views

app_name = "accountant"

urlpatterns = [
    path("api/mobile/health/", views.mobile_health, name="mobile_health"),
    path("api/mobile/fees/", views.mobile_fee_details, name="mobile_fee_details"),
    path("api/mobile/fees/summary/", views.mobile_fee_summary, name="mobile_fee_summary"),
    path("api/mobile/fees/invoices/", views.mobile_fee_invoices, name="mobile_fee_invoices"),
    path("api/mobile/fees/breakup/", views.mobile_fee_breakup, name="mobile_fee_breakup"),
    path("api/mobile/fees/categories/", views.mobile_fee_categories, name="mobile_fee_categories"),
    path("api/mobile/fees/payments/", views.mobile_payment_history, name="mobile_payment_history"),
    path("api/mobile/fees/payments/<int:payment_id>/receipt/", views.mobile_payment_receipt, name="mobile_payment_receipt"),
    path(
        "api/mobile/fees/payments/<int:payment_id>/receipt/download/",
        views.mobile_payment_receipt_download,
        name="mobile_payment_receipt_download",
    ),
]
