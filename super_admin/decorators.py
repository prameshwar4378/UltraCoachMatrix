from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .models import UserProfile
from .role_redirects import role_redirect_url


def role_required(*roles, allow_superuser=False):
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            if allow_superuser and request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            profile = getattr(request.user, "profile", None)
            if profile and profile.role in roles:
                return view_func(request, *args, **kwargs)

            return redirect(role_redirect_url(request.user))

        return wrapped

    return decorator


institute_admin_required = role_required(UserProfile.Role.INSTITUTE_ADMIN)
teacher_required = role_required(UserProfile.Role.TEACHER)
student_parent_required = role_required(UserProfile.Role.STUDENT_PARENT)
