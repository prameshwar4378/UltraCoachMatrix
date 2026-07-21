from django.urls import path

from . import views

app_name = "report_card"

urlpatterns = [
    path("", views.assessment_list, name="assessment_list"),
    path("create/", views.assessment_create, name="assessment_create"),
    path("<int:assessment_id>/", views.assessment_detail, name="assessment_detail"),
    path("<int:assessment_id>/edit/", views.assessment_update, name="assessment_update"),
    path("<int:assessment_id>/structure/", views.assessment_structure, name="assessment_structure"),
    path("<int:assessment_id>/subjects/create/", views.assessment_subject_create, name="assessment_subject_create"),
    path(
        "<int:assessment_id>/subjects/<int:assessment_subject_id>/edit/",
        views.assessment_subject_update,
        name="assessment_subject_update",
    ),
    path(
        "<int:assessment_id>/subjects/<int:assessment_subject_id>/delete/",
        views.assessment_subject_delete,
        name="assessment_subject_delete",
    ),
    path(
        "<int:assessment_id>/subjects/<int:assessment_subject_id>/components/create/",
        views.assessment_subject_component_create,
        name="assessment_subject_component_create",
    ),
    path(
        "<int:assessment_id>/subjects/<int:assessment_subject_id>/components/<int:component_id>/edit/",
        views.assessment_subject_component_update,
        name="assessment_subject_component_update",
    ),
    path(
        "<int:assessment_id>/subjects/<int:assessment_subject_id>/components/<int:component_id>/delete/",
        views.assessment_subject_component_delete,
        name="assessment_subject_component_delete",
    ),
    path(
        "<int:assessment_id>/marks/<int:assessment_subject_id>/",
        views.marks_entry,
        name="marks_entry",
    ),
    path(
        "<int:assessment_id>/marks/<int:assessment_subject_id>/template/",
        views.marks_entry_template,
        name="marks_entry_template",
    ),
    path(
        "<int:assessment_id>/marks/<int:assessment_subject_id>/import/",
        views.marks_entry_import,
        name="marks_entry_import",
    ),
    path("<int:assessment_id>/completion/", views.completion_summary, name="completion_summary"),
    path("<int:assessment_id>/generate/", views.generate_results, name="generate_results"),
    path("<int:assessment_id>/results/", views.results_preview, name="results_preview"),
    path("<int:assessment_id>/results/export/", views.results_export, name="results_export"),
    path(
        "<int:assessment_id>/results/<int:result_id>/pdf/",
        views.result_pdf_download,
        name="result_pdf_download",
    ),
    path("<int:assessment_id>/publish/", views.publish_results, name="publish_results"),
    path("<int:assessment_id>/lock/", views.lock_assessment, name="lock_assessment"),
    path("<int:assessment_id>/open-marks-entry/", views.open_marks_entry_view, name="open_marks_entry"),
]
