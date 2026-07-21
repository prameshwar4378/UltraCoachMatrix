from django.urls import path

from . import views

app_name = "report_card_student"

urlpatterns = [
    path("", views.published_report_cards, name="published_report_cards"),
    path("<int:result_id>/", views.published_report_card_detail, name="published_report_card_detail"),
    path("<int:result_id>/pdf/", views.published_report_card_pdf, name="published_report_card_pdf"),
]
