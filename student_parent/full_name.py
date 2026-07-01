from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist


_ORIGINAL_GET_FULL_NAME = User.get_full_name
_PATCHED_FLAG = "_ultracoach_student_full_name_patched"


def student_aware_get_full_name(user):
    try:
        student = user.student_profile
    except ObjectDoesNotExist:
        return _ORIGINAL_GET_FULL_NAME(user)

    return get_student_full_name(student) or _ORIGINAL_GET_FULL_NAME(user)


def get_student_full_name(student):
    user = student.user
    first_name = (user.first_name or "").strip()
    middle_name = (student.middle_name or student.father_name or "").strip()
    last_name = (user.last_name or "").strip()
    return " ".join(part for part in (first_name, middle_name, last_name) if part)


def patch_user_get_full_name():
    if getattr(User, _PATCHED_FLAG, False):
        return
    User.get_full_name = student_aware_get_full_name
    setattr(User, _PATCHED_FLAG, True)
