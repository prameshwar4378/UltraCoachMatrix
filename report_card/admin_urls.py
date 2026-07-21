from django.urls import path

from . import views

app_name = "report_card_admin"

urlpatterns = [
    path("", views.grade_rule_list, name="grade_rule_list"),
    path("create/", views.grade_rule_create, name="grade_rule_create"),
    path("<int:rule_id>/edit/", views.grade_rule_update, name="grade_rule_update"),
    path("<int:rule_id>/delete/", views.grade_rule_delete, name="grade_rule_delete"),
    path("assessments/<int:assessment_id>/unlock/", views.admin_unlock_assessment, name="admin_unlock_assessment"),
]
