from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path(
        "download/ultra-coach-matrix.apk",
        views.download_android_app,
        name="apk_download",
    ),
    path("contact-us/", views.contact_us, name="web_contact_us"),
    path("features/", views.features, name="web-features"),
    path("privacy-policy/", views.privacy_policy, name="web_privacy_policy"),
    path("terms/", views.terms, name="web_terms"),
    path("support/", views.support, name="web_support"),
]
