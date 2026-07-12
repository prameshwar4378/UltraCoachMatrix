from rest_framework.permissions import BasePermission


class IsTeacherMobileUser(BasePermission):
    message = "This endpoint is available only for teacher accounts."

    def has_permission(self, request, view):
        user = request.user
        profile = getattr(user, "profile", None)
        return bool(
            user
            and user.is_authenticated
            and user.is_active
            and profile
            and profile.role == "TEACHER"
            and profile.institute_id
        )
