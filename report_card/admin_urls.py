from django.urls import path

from . import views

app_name = "report_card_admin"

urlpatterns = [
    path("assessments/", views.admin_assessment_list, name="assessment_list"),
    path("assessments/create/", views.admin_assessment_create, name="assessment_create"),
    path("assessments/<int:assessment_id>/", views.admin_assessment_detail, name="assessment_detail"),
    path("assessments/<int:assessment_id>/edit/", views.admin_assessment_update, name="assessment_update"),
    path("assessments/<int:assessment_id>/completion/", views.admin_completion_dashboard, name="completion_dashboard"),
    path(
        "assessments/<int:assessment_id>/completion/subjects/<int:assessment_subject_id>/marks/",
        views.admin_marks_grid,
        name="marks_grid",
    ),
    path("assessments/<int:assessment_id>/results/", views.admin_results_preview, name="results_preview"),
    path("assessments/<int:assessment_id>/results/generate/", views.admin_generate_results, name="generate_results"),
    path("assessments/<int:assessment_id>/results/export/", views.admin_results_export, name="results_export"),
    path(
        "assessments/<int:assessment_id>/results/<int:result_id>/pdf/",
        views.admin_result_pdf_download,
        name="result_pdf_download",
    ),
    path("assessments/<int:assessment_id>/results/publish/", views.admin_publish_results, name="publish_results"),
    path("assessments/<int:assessment_id>/results/lock/", views.admin_lock_assessment, name="lock_assessment"),
    path("assessments/<int:assessment_id>/structure/", views.admin_assessment_structure, name="assessment_structure"),
    path("assessments/<int:assessment_id>/open-marks-entry/", views.admin_open_marks_entry, name="open_marks_entry"),
    path(
        "assessments/<int:assessment_id>/subjects/create/",
        views.admin_assessment_subject_create,
        name="assessment_subject_create",
    ),
    path(
        "assessments/<int:assessment_id>/subjects/<int:assessment_subject_id>/edit/",
        views.admin_assessment_subject_update,
        name="assessment_subject_update",
    ),
    path(
        "assessments/<int:assessment_id>/subjects/<int:assessment_subject_id>/delete/",
        views.admin_assessment_subject_delete,
        name="assessment_subject_delete",
    ),
    path("allocations/", views.allocation_list, name="allocation_list"),
    path("allocations/create/", views.allocation_create, name="allocation_create"),
    path("allocations/<int:allocation_id>/edit/", views.allocation_update, name="allocation_update"),
    path("allocations/<int:allocation_id>/delete/", views.allocation_delete, name="allocation_delete"),
    path("", views.grade_rule_list, name="grade_rule_list"),
    path("create/", views.grade_rule_create, name="grade_rule_create"),
    path("create-defaults/", views.grade_rule_create_defaults, name="grade_rule_create_defaults"),
    path("<int:rule_id>/edit/", views.grade_rule_update, name="grade_rule_update"),
    path("<int:rule_id>/delete/", views.grade_rule_delete, name="grade_rule_delete"),
    path("assessments/<int:assessment_id>/unlock/", views.admin_unlock_assessment, name="admin_unlock_assessment"),
]
