from django.utils import timezone

from .models import InstituteSubscription
from .subscription_warning import subscription_expiry_warning


def subscription_context(request):
    warning = subscription_expiry_warning(request)
    subscription = (
        getattr(request.user.profile.institute, "subscription", None)
        if request.user.is_authenticated
        and hasattr(request.user, "profile")
        and request.user.profile.institute_id
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
        "is_trial_active": bool(
            subscription
            and subscription.plan == InstituteSubscription.Plan.FREE_TRIAL
            and subscription.is_active
        ),
        "trial_days_remaining": days_remaining,
    }
