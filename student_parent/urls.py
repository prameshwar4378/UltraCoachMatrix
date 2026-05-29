from django.urls import path

from . import views

app_name = "student_parent"

urlpatterns = [
    path("download-app/", views.download_app, name="download_app"),
    path("api/mobile/homework/", views.mobile_homework_planner, name="mobile_homework_planner"),
    path("api/mobile/devices/register/", views.mobile_register_device, name="mobile_register_device"),
    path("api/mobile/devices/unregister/", views.mobile_unregister_device, name="mobile_unregister_device"),
    path("api/mobile/notifications/", views.mobile_notifications, name="mobile_notifications"),
    path(
        "api/mobile/homework/document/download/",
        views.mobile_homework_document_download,
        name="mobile_homework_document_download",
    ),
]
