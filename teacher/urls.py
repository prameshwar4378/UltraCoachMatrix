from django.urls import path

from . import views

app_name = "teacher"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("attendance/", views.attendance, name="attendance"),
    path("homework/", views.homework, name="homework"),
    path("homework/create/", views.homework_create, name="homework_create"),
    path("exams/", views.exams, name="exams"),
    path("exams/create/", views.exam_create, name="exam_create"),
    path("results/", views.results, name="results"),
    path("results/create/", views.result_create, name="result_create"),
]
