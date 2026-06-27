from django.utils import timezone

from .models import InstituteSubscription
from .subscription_warning import subscription_expiry_warning


def subscription_context(request):
    warning = subscription_expiry_warning(request)
    profile = (
        request.user.profile
        if request.user.is_authenticated
        and hasattr(request.user, "profile")
        and request.user.profile.institute_id
        else None
    )
    institute = profile.institute if profile else None
    subscription = (
        getattr(institute, "subscription", None)
        if institute
        else None
    )
    days_remaining = (
        max((subscription.ends_on - timezone.localdate()).days, 0)
        if subscription and subscription.ends_on
        else None
    )
    return {
        "subscription_expiry_warning": warning,
        "current_subscription": subscription,
        "current_school": institute,
        "current_school_user": profile,
        "is_trial_active": bool(
            subscription
            and subscription.plan == InstituteSubscription.Plan.FREE_TRIAL
            and subscription.is_active
        ),
        "trial_days_remaining": days_remaining,
    }
