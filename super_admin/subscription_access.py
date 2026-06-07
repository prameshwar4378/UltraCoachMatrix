from .models import Institute, UserProfile


def institute_access_status(user):
    if not user or not user.is_authenticated or user.is_superuser:
        return True, ""

    profile = getattr(user, "profile", None)
    if not profile or profile.role == UserProfile.Role.SUPER_ADMIN or not profile.institute_id:
        return True, ""

    institute = profile.institute
    if institute.status not in {Institute.Status.ACTIVE, Institute.Status.TRIAL}:
        return False, "This institute account is not active."

    subscription = getattr(institute, "subscription", None)
    if subscription and not subscription.is_active:
        return False, "Your software subscription has expired."

    return True, ""
