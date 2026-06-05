from django.urls import path

from . import views

app_name = "teacher"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("attendance/", views.attendance, name="attendance"),
    path("attendance/export/", views.attendance_export, name="attendance_export"),
    path("homework/", views.homework, name="homework"),
    path("homework/create/", views.homework_create, name="homework_create"),
    path("homework/<int:pk>/edit/", views.homework_update, name="homework_update"),
    path("homework/<int:pk>/delete/", views.homework_delete, name="homework_delete"),
    path("exams/", views.exams, name="exams"),
    path("exams/create/", views.exam_create, name="exam_create"),
    path("exams/<int:pk>/edit/", views.exam_update, name="exam_update"),
    path("exams/<int:pk>/questions/", views.exam_questions, name="exam_questions"),
    path("exams/<int:pk>/questions/create/", views.exam_question_create, name="exam_question_create"),
    path("exams/<int:pk>/questions/import/", views.exam_question_bulk_import, name="exam_question_bulk_import"),
    path(
        "exams/<int:pk>/questions/import-template/",
        views.exam_question_import_template,
        name="exam_question_import_template",
    ),
    path(
        "exams/<int:exam_pk>/questions/<int:question_pk>/edit/",
        views.exam_question_update,
        name="exam_question_update",
    ),
    path("exams/<int:pk>/submissions/", views.exam_submissions, name="exam_submissions"),
    path("exams/<int:pk>/publish/", views.exam_publish, name="exam_publish"),
    path(
        "exams/<int:exam_pk>/submissions/<int:attempt_pk>/manage/",
        views.exam_attempt_manage,
        name="exam_attempt_manage",
    ),
    path(
        "exams/<int:exam_pk>/submissions/<int:attempt_pk>/reset/",
        views.exam_attempt_reset,
        name="exam_attempt_reset",
    ),
    path("exams/<int:pk>/results/visibility/", views.exam_toggle_result_publish, name="exam_toggle_result_publish"),
    path("results/", views.results, name="results"),
    path("results/create/", views.result_create, name="result_create"),
]
