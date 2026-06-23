from django.apps import AppConfig


class SuperAdminConfig(AppConfig):
    name = 'super_admin'

    def ready(self):
        from . import signals  # noqa: F401
