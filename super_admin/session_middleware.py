from .session_security import capture_session_metadata


class SessionSecurityMetadataMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        capture_session_metadata(request)
        return self.get_response(request)
