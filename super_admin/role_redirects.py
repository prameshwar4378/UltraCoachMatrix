from django.urls import reverse_lazy

from .models import UserProfile


def role_redirect_url(user):
    profile = getattr(user, "profile", None)
    role = profile.role if profile else None

    if user.is_superuser or role == UserProfile.Role.SUPER_ADMIN:
        return reverse_lazy("admin:index")
    if role == UserProfile.Role.TEACHER:
        return reverse_lazy("teacher:dashboard")
    if role == UserProfile.Role.STUDENT_PARENT:
        return reverse_lazy("student_parent:download_app")
    if role == UserProfile.Role.INSTITUTE_ADMIN and not profile.onboarding_completed_at:
        return reverse_lazy("institute_admin:software_tour")
    return reverse_lazy("institute_admin:dashboard")
