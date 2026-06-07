from datetime import timedelta
import hashlib

from django.contrib.sessions.models import Session
from django.utils import timezone
from django.utils.dateparse import parse_datetime


SESSION_META_KEY = "_security_session"
LAST_ACTIVITY_WRITE_INTERVAL = timedelta(minutes=5)


def client_ip(request):
    return (request.META.get("REMOTE_ADDR") or "").strip() or "Unknown"


def parse_user_agent(user_agent):
    value = user_agent or ""
    lower_value = value.lower()

    if "edg/" in lower_value:
        browser = "Microsoft Edge"
    elif "opr/" in lower_value or "opera" in lower_value:
        browser = "Opera"
    elif "chrome/" in lower_value and "chromium" not in lower_value:
        browser = "Google Chrome"
    elif "firefox/" in lower_value:
        browser = "Mozilla Firefox"
    elif "safari/" in lower_value and "chrome/" not in lower_value:
        browser = "Safari"
    else:
        browser = "Unknown browser"

    if "windows" in lower_value:
        operating_system = "Windows"
    elif "android" in lower_value:
        operating_system = "Android"
    elif "iphone" in lower_value or "ipad" in lower_value:
        operating_system = "iOS"
    elif "mac os" in lower_value or "macintosh" in lower_value:
        operating_system = "macOS"
    elif "linux" in lower_value:
        operating_system = "Linux"
    else:
        operating_system = "Unknown OS"

    if "ipad" in lower_value or "tablet" in lower_value:
        device_type = "Tablet"
    elif "mobile" in lower_value or "android" in lower_value or "iphone" in lower_value:
        device_type = "Mobile"
    else:
        device_type = "Computer"

    return browser, operating_system, device_type


def session_identifier(session_key):
    return hashlib.sha256(session_key.encode("utf-8")).hexdigest()


def capture_session_metadata(request, force=False):
    if not request.user.is_authenticated or not request.session.session_key:
        return

    now = timezone.now()
    metadata = request.session.get(SESSION_META_KEY, {})
    last_activity = parse_datetime(metadata.get("last_activity", ""))
    should_update = force or not last_activity or now - last_activity >= LAST_ACTIVITY_WRITE_INTERVAL
    if not should_update:
        return

    browser, operating_system, device_type = parse_user_agent(
        request.META.get("HTTP_USER_AGENT", "")
    )
    request.session[SESSION_META_KEY] = {
        "login_at": metadata.get("login_at") or now.isoformat(),
        "last_activity": now.isoformat(),
        "ip_address": metadata.get("ip_address") or client_ip(request),
        "browser": metadata.get("browser") or browser,
        "operating_system": metadata.get("operating_system") or operating_system,
        "device_type": metadata.get("device_type") or device_type,
    }
    request.session.modified = True


def user_web_sessions(user, current_session=None):
    sessions = []
    active_sessions = Session.objects.filter(expire_date__gte=timezone.now())
    for session in active_sessions.iterator():
        try:
            decoded = session.get_decoded()
        except Exception:
            continue
        if str(decoded.get("_auth_user_id")) != str(user.pk):
            continue

        metadata = decoded.get(SESSION_META_KEY, {})
        if current_session and session.session_key == current_session.session_key:
            metadata = current_session.get(SESSION_META_KEY, metadata)
        sessions.append(
            {
                "session_key": session.session_key,
                "identifier": session_identifier(session.session_key),
                "login_at": parse_datetime(metadata.get("login_at", "")),
                "last_activity": parse_datetime(metadata.get("last_activity", "")),
                "ip_address": metadata.get("ip_address") or "Unknown",
                "browser": metadata.get("browser") or "Unknown browser",
                "operating_system": metadata.get("operating_system") or "Unknown OS",
                "device_type": metadata.get("device_type") or "Unknown device",
            }
        )

    return sorted(
        sessions,
        key=lambda item: item["last_activity"] or item["login_at"] or timezone.now(),
        reverse=True,
    )
