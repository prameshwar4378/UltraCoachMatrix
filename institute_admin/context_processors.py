from .forms import get_academic_year_label, get_or_create_academic_year
from .lookup_cache import get_cached_academic_years, invalidate_academic_years_cache
from super_admin.models import UserProfile


def academic_year_context(request):
    cached_context = getattr(request, "_academic_year_context", None)
    if cached_context is not None:
        return cached_context

    if not request.user.is_authenticated:
        return {}
    profile = getattr(request.user, "profile", None)
    allowed_roles = {UserProfile.Role.INSTITUTE_ADMIN, UserProfile.Role.TEACHER}
    if not profile or profile.role not in allowed_roles or not profile.institute_id:
        return {}

    institute = profile.institute
    academic_years = get_cached_academic_years(institute.pk)

    selected_id = request.session.get("academic_year_id")
    selected_year = getattr(request, "_selected_academic_year", None)
    if selected_year and selected_year.institute_id != institute.pk:
        selected_year = None

    if selected_id:
        selected_year = next((year for year in academic_years if str(year.pk) == str(selected_id)), selected_year)

    if not selected_year:
        current_label = get_academic_year_label()
        selected_year = next((year for year in academic_years if year.name == current_label and year.is_active), None)
        selected_year = selected_year or next((year for year in academic_years if year.name == current_label), None)

    if not selected_year and academic_years:
        selected_year = next((year for year in academic_years if year.is_active), academic_years[0])

    if not selected_year:
        selected_year = get_or_create_academic_year(institute, get_academic_year_label())
        invalidate_academic_years_cache(institute.pk)
        academic_years = [selected_year]

    if str(request.session.get("academic_year_id", "")) != str(selected_year.pk):
        request.session["academic_year_id"] = selected_year.pk

    request._selected_academic_year = selected_year
    context = {
        "academic_years": academic_years,
        "selected_academic_year": selected_year,
    }
    request._academic_year_context = context
    return context
