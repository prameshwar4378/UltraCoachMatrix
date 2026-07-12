from rest_framework import authentication, exceptions

from super_admin.mobile_auth import bearer_user


class MobileBearerAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        authorization = request.headers.get("Authorization", "")
        if not authorization:
            return None
        if not authorization.startswith(f"{self.keyword} "):
            raise exceptions.AuthenticationFailed("Invalid authorization header.")
        user = bearer_user(request)
        if not user:
            raise exceptions.AuthenticationFailed("Invalid or expired access token.")
        return user, None

    def authenticate_header(self, request):
        return self.keyword
