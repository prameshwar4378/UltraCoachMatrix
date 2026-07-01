from django.apps import AppConfig


class StudentParentConfig(AppConfig):
    name = 'student_parent'

    def ready(self):
        from .full_name import patch_user_get_full_name

        patch_user_get_full_name()
