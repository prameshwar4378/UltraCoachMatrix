from urllib.parse import urlencode

from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

from .mobile_auth import bearer_identity_user
from .subscription_access import institute_access_status


class InstituteSubscriptionMiddleware:
    exempt_prefixes = (
        "/admin/",
        "/static/",
        "/media/",
    )
    exempt_paths = {
        "/login/",
        "/logout/",
        "/signup/",
        "/subscription-expired/",
        "/institute/billing/",
        "/institute/security/",
        "/institute/help/",
    }
    exempt_api_paths = {
        "/api/auth/login/",
        "/api/auth/logout/",
        "/api/mobile/auth/login/",
        "/api/mobile/auth/logout/",
        "/api/mobile/auth/me/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def is_exempt(self, request):
        path = request.path_info
        return (
            path in self.exempt_paths
            or path in self.exempt_api_paths
            or path.startswith(self.exempt_prefixes)
            or path.startswith("/institute/billing/payments/")
        )

    def __call__(self, request):
        access_user = request.user if request.user.is_authenticated else None
        if (
            access_user is None
            and request.path_info.startswith("/api/")
            and not self.is_exempt(request)
        ):
            access_user = bearer_identity_user(request)

        if access_user is not None and not self.is_exempt(request):
            allowed, message = institute_access_status(access_user)
            if not allowed:
                if request.path_info.startswith("/api/"):
                    return JsonResponse(
                        {
                            "detail": message,
                            "code": "subscription_expired",
                            "renewal_required": True,
                        },
                        status=403,
                    )
                query = urlencode({"reason": message})
                return redirect(f"{reverse('subscription_expired')}?{query}")
        return self.get_response(request)
