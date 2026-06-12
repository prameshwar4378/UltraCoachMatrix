from django.apps import AppConfig


class InstituteAdminConfig(AppConfig):
    name = 'institute_admin'

    def ready(self):
        from . import signals  # noqa: F401
