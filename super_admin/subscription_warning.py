from django.utils import timezone

from .models import UserProfile


SESSION_KEY = "subscription_expiry_warning_ack"
WARNING_DAYS = 5


def subscription_expiry_warning(request):
    if not request.user.is_authenticated or request.user.is_superuser:
        return None

    profile = getattr(request.user, "profile", None)
    if not profile or not profile.institute_id:
        return None
    subscription = getattr(profile.institute, "subscription", None)
    if not subscription or not subscription.ends_on:
        return None

    today = timezone.localdate()
    days_remaining = (subscription.ends_on - today).days
    if days_remaining < 0 or days_remaining > WARNING_DAYS:
        return None

    acknowledgement = f"{subscription.ends_on.isoformat()}:{today.isoformat()}"
    return {
        "acknowledgement": acknowledgement,
        "days_remaining": days_remaining,
        "expires_on": subscription.ends_on,
        "plan_name": subscription.get_plan_display(),
        "is_institute_admin": profile.role == UserProfile.Role.INSTITUTE_ADMIN,
        "show": request.session.get(SESSION_KEY) != acknowledgement,
    }
