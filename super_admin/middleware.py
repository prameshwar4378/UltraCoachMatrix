from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .subscription_access import institute_access_status


class InstituteSubscriptionMiddleware:
    exempt_prefixes = (
        "/admin/",
        "/login/",
        "/logout/",
        "/signup/",
        "/subscription-expired/",
        "/institute/billing/",
        "/institute/security/",
        "/institute/help/",
        "/static/",
        "/media/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not request.path.startswith(self.exempt_prefixes):
            allowed, message = institute_access_status(request.user)
            if not allowed:
                if request.path.startswith("/api/"):
                    return JsonResponse({"detail": message}, status=403)
                return redirect(f"{reverse('subscription_expired')}?reason={message}")
        return self.get_response(request)
