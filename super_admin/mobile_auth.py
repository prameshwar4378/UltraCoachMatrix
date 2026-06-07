from datetime import timedelta
import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.utils import timezone

from .models import MobileRefreshToken
from .subscription_access import institute_access_status


ACCESS_TOKEN_SALT = "ultracoachmatrix.mobile.access"
ACCESS_TOKEN_SECONDS = getattr(settings, "MOBILE_ACCESS_TOKEN_SECONDS", 15 * 60)
REFRESH_TOKEN_DAYS = getattr(settings, "MOBILE_REFRESH_TOKEN_DAYS", 3650)


def hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user):
    profile = getattr(user, "profile", None)
    payload = {
        "user_id": user.pk,
        "username": user.get_username(),
        "role": profile.role if profile else None,
        "institute_id": profile.institute_id if profile else None,
    }
    return signing.dumps(payload, salt=ACCESS_TOKEN_SALT)


def verify_access_token(token):
    try:
        payload = signing.loads(token, salt=ACCESS_TOKEN_SALT, max_age=ACCESS_TOKEN_SECONDS)
    except signing.BadSignature:
        return None
    user = User.objects.filter(pk=payload.get("user_id"), is_active=True).first()
    if not user:
        return None
    allowed, _message = institute_access_status(user)
    if not allowed:
        return None
    return user


def create_refresh_token(user):
    raw_token = secrets.token_urlsafe(48)
    MobileRefreshToken.objects.create(
        user=user,
        token_hash=hash_token(raw_token),
        expires_at=timezone.now() + timedelta(days=REFRESH_TOKEN_DAYS),
    )
    return raw_token


def get_active_refresh_token(raw_token):
    token_hash = hash_token(raw_token)
    refresh_token = MobileRefreshToken.objects.select_related("user").filter(token_hash=token_hash).first()
    if not refresh_token or not refresh_token.is_active or not refresh_token.user.is_active:
        return None
    allowed, _message = institute_access_status(refresh_token.user)
    if not allowed:
        return None
    return refresh_token


def revoke_refresh_token(raw_token):
    refresh_token = get_active_refresh_token(raw_token)
    if not refresh_token:
        return False
    refresh_token.revoked_at = timezone.now()
    refresh_token.save(update_fields=["revoked_at"])
    return True


def bearer_user(request):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        return None
    return verify_access_token(token)
