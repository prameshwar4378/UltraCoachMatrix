from .forms import get_academic_year_label, get_or_create_academic_year
from .models import AcademicYear
from super_admin.models import UserProfile


def academic_year_context(request):
    if not request.user.is_authenticated:
        return {}
    profile = getattr(request.user, "profile", None)
    allowed_roles = {UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.TEACHER}
    if not profile or profile.role not in allowed_roles or not profile.institute_id:
        return {}

    institute = profile.institute
    current_label = get_academic_year_label()
    year_parts = int(current_label.split("-", 1)[0])
    for start_year in range(year_parts - 2, year_parts + 4):
        get_or_create_academic_year(institute, f"{start_year}-{str(start_year + 1)[-2:]}")

    selected_id = request.session.get("academic_year_id")
    selected_year = None
    if selected_id:
        selected_year = AcademicYear.objects.filter(pk=selected_id, institute=institute, is_active=True).first()
    if not selected_year:
        selected_year = get_or_create_academic_year(institute, current_label)
        request.session["academic_year_id"] = selected_year.pk

    return {
        "academic_years": AcademicYear.objects.filter(institute=institute, is_active=True),
        "selected_academic_year": selected_year,
    }
