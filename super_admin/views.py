import json

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.contrib.auth.views import LoginView, LogoutView
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import InstituteSignupForm
from .mobile_auth import (
    bearer_identity_user,
    bearer_user,
    create_access_token,
    create_refresh_token,
    get_active_refresh_token,
    revoke_refresh_token,
)
from .role_redirects import role_redirect_url
from .subscription_access import institute_access_status
from .subscription_warning import SESSION_KEY, subscription_expiry_warning
from student_parent.models import StudentAcademicSession
from UltraCoachMatrix.email_notifications import on_commit_email, send_institute_welcome

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

@method_decorator(csrf_exempt, name="dispatch")
class RoleLoginView(LoginView):
    template_name = "super_admin/login.html"

    def get_success_url(self):
        allowed, _message = institute_access_status(self.request.user)
        if not allowed:
            return str(reverse("subscription_expired"))
        return role_redirect_url(self.request.user)

@method_decorator(csrf_exempt, name="dispatch")
class RoleLogoutView(LogoutView):
    pass


def role_home(request):
    if not request.user.is_authenticated:
        return redirect("login")
    return redirect(role_redirect_url(request.user))


def subscription_expired(request):
    reason = request.GET.get("reason") or "Your software subscription has expired."
    profile = getattr(request.user, "profile", None) if request.user.is_authenticated else None
    institute = profile.institute if profile and profile.institute_id else None
    subscription = getattr(institute, "subscription", None) if institute else None
    can_renew = bool(
        profile
        and profile.role == profile.Role.INSTITUTE_ADMIN
        and institute
    )
    return render(
        request,
        "super_admin/subscription_expired.html",
        {
            "reason": reason,
            "institute": institute,
            "subscription": subscription,
            "can_renew": can_renew,
        },
    )


@require_POST
def acknowledge_subscription_expiry(request):
    if not request.user.is_authenticated:
        return redirect("login")

    warning = subscription_expiry_warning(request)
    if warning:
        request.session[SESSION_KEY] = warning["acknowledgement"]

    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("school_dashboard")
    return redirect(next_url)


def _json_request_data(request):
    if request.content_type == "application/json":
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            return None
    return request.POST


def _user_payload(user):
    profile = getattr(user, "profile", None)
    allowed, access_message = institute_access_status(user)
    return {
        "id": user.pk,
        "username": user.get_username(),
        "email": user.email,
        "name": user.get_full_name(),
        "role": profile.role if profile else None,
        "institute_id": profile.institute_id if profile else None,
        "subscription_access_allowed": allowed,
        "subscription_access_message": access_message,
    }


def _token_payload(user):
    return {
        "access": create_access_token(user),
        "refresh": create_refresh_token(user),
        "token_type": "Bearer",
        "expires_in": 15 * 60,
        "user": _user_payload(user),
    }


def signup(request):
    if request.method == "POST":
        form = InstituteSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            on_commit_email(
                send_institute_welcome,
                user.pk,
                form.cleaned_data["password1"],
            )
            login(request, user)
            return redirect(role_redirect_url(user))
    else:
        form = InstituteSignupForm()

    return render(request, "super_admin/signup.html", {"form": form})


@csrf_exempt
@require_POST
def api_login(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)
    allowed, message = institute_access_status(user)
    if not allowed:
        return JsonResponse({"detail": message}, status=403)

    login(request, user)
    return JsonResponse(
        {
            "detail": "Login successful.",
            "redirect_url": str(role_redirect_url(user)),
            "user": _user_payload(user),
        }
    )


@csrf_exempt
@require_POST
def api_logout(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication credentials were not provided."}, status=401)

    logout(request)
    return JsonResponse({"detail": "Logout successful."})


@csrf_exempt
@require_POST
def mobile_login(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return JsonResponse({"detail": "Username and password are required."}, status=400)

    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "Invalid username or password."}, status=401)
    allowed, message = institute_access_status(user)
    if not allowed:
        return JsonResponse({"detail": message}, status=403)

    return JsonResponse(_token_payload(user))


@csrf_exempt
@require_POST
def mobile_token_refresh(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    refresh = data.get("refresh") or ""
    refresh_token = get_active_refresh_token(refresh, check_institute_access=False)
    if not refresh_token:
        return JsonResponse({"detail": "Invalid or expired refresh token."}, status=401)

    return JsonResponse(
        {
            "access": create_access_token(refresh_token.user),
            "token_type": "Bearer",
            "expires_in": 15 * 60,
            "user": _user_payload(refresh_token.user),
        }
    )


@csrf_exempt
@require_POST
def mobile_logout(request):
    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    refresh = data.get("refresh") or ""
    if not revoke_refresh_token(refresh):
        return JsonResponse({"detail": "Invalid or expired refresh token."}, status=401)
    return JsonResponse({"detail": "Logout successful."})


def mobile_me(request):
    user = bearer_identity_user(request)
    if not user:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)
    return JsonResponse({"user": _user_payload(user)})


@csrf_exempt
@require_POST
def mobile_change_password(request):
    user = bearer_user(request)
    if not user:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    data = _json_request_data(request)
    if data is None:
        return JsonResponse({"detail": "Invalid JSON body."}, status=400)

    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    confirm_password = data.get("confirm_password") or ""
    if not current_password or not new_password or not confirm_password:
        return JsonResponse({"detail": "All password fields are required."}, status=400)
    if not user.check_password(current_password):
        return JsonResponse({"detail": "Current password is incorrect."}, status=400)
    if new_password != confirm_password:
        return JsonResponse({"detail": "New password and confirm password do not match."}, status=400)

    try:
        validate_password(new_password, user=user)
    except ValidationError as error:
        return JsonResponse({"detail": " ".join(error.messages)}, status=400)

    user.set_password(new_password)
    user.save(update_fields=["password"])
    return JsonResponse({"detail": "Password updated successfully."})


def _absolute_file_url(request, file_field):
    if not file_field:
        return ""
    try:
        return request.build_absolute_uri(file_field.url)
    except ValueError:
        return ""


def _mobile_profile_payload(student, request):
    sessions = (
        StudentAcademicSession.objects.filter(
            Q(student=student) | Q(enrollments__student=student)
        )
        .select_related("academic_year", "institute")
        .prefetch_related("enrollments__batch", "enrollments__courses")
        .distinct()
        .order_by("-academic_year__start_date", "-pk")
    )
    selected_session_id = (request.GET.get("academic_session_id") or "").strip()
    active_session = None
    if selected_session_id:
        active_session = sessions.filter(pk=selected_session_id).first()
    if not active_session:
        active_session = sessions.first()
    guardians = student.guardians.all()
    documents = student.documents.all()

    return {
            "student": {
                "id": student.pk,
                "admission_number": student.admission_number,
                "name": student.user.get_full_name() or student.user.username,
                "username": student.user.username,
                "email": student.user.email,
                "phone": getattr(getattr(student.user, "profile", None), "phone", ""),
                "institute": {"id": student.institute_id, "name": student.institute.name},
                "profile_image_url": _absolute_file_url(request, student.profile_image),
                "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else None,
                "joined_on": student.joined_on.isoformat() if student.joined_on else None,
                "address": student.address,
                "current_school_name": student.current_school_name,
                "current_school_address": student.current_school_address,
                "previous_school_name": student.previous_school_name,
                "previous_class": student.previous_class,
                "is_active": student.is_active,
            },
            "active_session": {
                "id": active_session.pk,
                "admission_number": active_session.admission_number,
                "academic_year": active_session.academic_year.name,
                "status": active_session.status,
                "joined_on": active_session.joined_on.isoformat() if active_session.joined_on else None,
                "current_school_name": active_session.current_school_name,
                "current_school_address": active_session.current_school_address,
                "previous_school_name": active_session.previous_school_name,
                "previous_class": active_session.previous_class,
            }
            if active_session
            else None,
            "academic_sessions": [
                {
                    "id": session.pk,
                    "admission_number": session.admission_number,
                    "academic_year": session.academic_year.name,
                    "status": session.status,
                    "joined_on": session.joined_on.isoformat() if session.joined_on else None,
                    "current_school_name": session.current_school_name,
                    "current_school_address": session.current_school_address,
                    "previous_school_name": session.previous_school_name,
                    "previous_class": session.previous_class,
                }
                for session in sessions
            ],
            "enrollments": [
                {
                    "id": enrollment.pk,
                    "academic_session_id": enrollment.academic_session_id,
                    "academic_year": session.academic_year.name,
                    "batch": {
                        "id": enrollment.batch_id,
                        "name": enrollment.batch.name,
                        "weekly_timetable": enrollment.batch.weekly_timetable,
                    },
                    "courses": [{"id": course.pk, "name": course.name} for course in enrollment.courses.all()],
                    "total_course_fee": str(enrollment.total_course_fee),
                    "custom_fee_amount": str(enrollment.custom_fee_amount) if enrollment.custom_fee_amount is not None else None,
                    "status": enrollment.status,
                    "enrolled_on": enrollment.enrolled_on.isoformat() if enrollment.enrolled_on else None,
                }
                for session in sessions
                for enrollment in session.enrollments.exclude(status="CANCELLED").all()
            ],
            "guardians": [
                {
                    "id": guardian.pk,
                    "name": guardian.name,
                    "relation": guardian.relation,
                    "phone": guardian.phone,
                    "email": guardian.email,
                    "is_primary": guardian.is_primary,
                }
                for guardian in guardians
            ],
            "documents": [
                {
                    "id": document.pk,
                    "title": document.title,
                    "document_type": document.document_type,
                    "document_type_display": document.get_document_type_display(),
                    "file_url": _absolute_file_url(request, document.file),
                    "uploaded_at": document.uploaded_at.isoformat() if document.uploaded_at else None,
                    "note": document.note,
                }
                for document in documents
            ],
        }


def mobile_profile(request):
    user = bearer_user(request)
    if not user:
        return JsonResponse({"detail": "Invalid or expired access token."}, status=401)

    student = getattr(user, "student_profile", None)
    if not student:
        return JsonResponse({"detail": "No student profile is linked to this user."}, status=404)

    return JsonResponse(_mobile_profile_payload(student, request))
