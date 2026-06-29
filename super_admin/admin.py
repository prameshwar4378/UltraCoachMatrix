from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, User
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone

from institute_admin.models import SupportTicket

from .models import (
    Institute,
    InstituteSubscription,
    SubscriptionPayment,
    UserProfile,
)


admin.site.site_header = "UltraCoachMatrix Administration"
admin.site.site_title = "UltraCoachMatrix Admin"
admin.site.index_title = "Institute Accounts and Subscriptions"


class NonStudentInstituteFilter(admin.SimpleListFilter):
    title = "institute"
    parameter_name = "non_student_institute"

    def lookups(self, request, model_admin):
        return [
            (str(institute.pk), institute.name)
            for institute in Institute.objects.order_by("name")
        ]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset
        return queryset.filter(
            Q(profile__institute_id=value) | Q(teacher_profile__institute_id=value)
        )


def _non_student_users_queryset():
    return (
        User.objects.select_related("profile__institute", "teacher_profile__institute")
        .exclude(student_profile__isnull=False)
        .exclude(profile__role=UserProfile.Role.STUDENT_PARENT)
        .distinct()
        .order_by("username")
    )


def _user_role(user):
    profile = getattr(user, "profile", None)
    if profile:
        return profile.get_role_display()
    if getattr(user, "teacher_profile", None):
        return "Teacher"
    if user.is_superuser:
        return "Superuser"
    if user.is_staff:
        return "Staff"
    return "-"


def _user_institute(user):
    profile = getattr(user, "profile", None)
    if profile and profile.institute_id:
        return profile.institute
    teacher_profile = getattr(user, "teacher_profile", None)
    if teacher_profile and teacher_profile.institute_id:
        return teacher_profile.institute
    return None


def all_non_student_users_view(request):
    queryset = _non_student_users_queryset()
    search = request.GET.get("q", "").strip()
    institute_id = request.GET.get("institute", "").strip()
    active = request.GET.get("active", "").strip()

    if search:
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(email__icontains=search)
            | Q(profile__phone__icontains=search)
            | Q(profile__institute__name__icontains=search)
            | Q(teacher_profile__institute__name__icontains=search)
        )
    if institute_id:
        queryset = queryset.filter(
            Q(profile__institute_id=institute_id)
            | Q(teacher_profile__institute_id=institute_id)
        )
    if active == "active":
        queryset = queryset.filter(is_active=True)
    elif active == "inactive":
        queryset = queryset.filter(is_active=False)

    paginator = Paginator(queryset, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    users = [
        {
            "user": user,
            "role": _user_role(user),
            "institute": _user_institute(user),
        }
        for user in page_obj.object_list
    ]
    context = {
        **admin.site.each_context(request),
        "title": "All users except students",
        "users": users,
        "page_obj": page_obj,
        "paginator": paginator,
        "search": search,
        "selected_institute": institute_id,
        "selected_active": active,
        "institutes": Institute.objects.order_by("name"),
        "opts": User._meta,
    }
    return TemplateResponse(request, "admin/all_non_student_users.html", context)


class InstituteAdminUserInline(admin.TabularInline):
    model = UserProfile
    extra = 0
    fields = ("user", "role", "phone", "login_active")
    autocomplete_fields = ("user",)
    readonly_fields = ("login_active",)
    verbose_name = "Institute login"
    verbose_name_plural = "Institute logins"

    @admin.display(boolean=True, description="Login active")
    def login_active(self, obj):
        return obj.user.is_active if obj and obj.user_id else None


class InstituteSubscriptionInline(admin.StackedInline):
    model = InstituteSubscription
    extra = 0
    max_num = 1
    fields = ("plan", "starts_on", "ends_on", "notes")
    verbose_name = "Plan and software access"
    verbose_name_plural = "Plan, start date and expiry date"


class SubscriptionPaymentInline(admin.TabularInline):
    model = SubscriptionPayment
    extra = 0
    fields = ("amount", "paid_on", "method", "transaction_id", "notes")
    ordering = ("-paid_on", "-pk")
    verbose_name = "Payment transaction"
    verbose_name_plural = "Payment history / transactions"


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "logo_preview",
        "institute_type",
        "owner_name",
        "phone",
        "subscription_plan",
        "effective_status",
        "subscription_start",
        "subscription_expiry",
        "days_remaining",
        "admin_login",
    )
    list_filter = (
        "subscription__plan",
        "institute_type",
        "status",
        "subscription__starts_on",
        "subscription__ends_on",
    )
    search_fields = ("name", "code", "owner_name", "phone", "email")
    prepopulated_fields = {"code": ("name",)}
    readonly_fields = ("logo_preview", "created_at", "updated_at")
    inlines = (
        InstituteSubscriptionInline,
        SubscriptionPaymentInline,
        InstituteAdminUserInline,
    )
    actions = ("activate_accounts", "start_trials", "suspend_accounts")
    fieldsets = (
        (
            "School details",
            {
                "fields": (
                    "name",
                    "code",
                    "institute_type",
                    "logo",
                    "logo_preview",
                    "owner_name",
                    "phone",
                    "email",
                    "address",
                )
            },
        ),
        (
            "Account control",
            {
                "fields": ("status", "internal_notes"),
                "description": (
                    "Plan and expiry are managed in the Plan and software access section below. "
                    "Expired access is blocked automatically."
                ),
            },
        ),
        ("Audit", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="Logo")
    def logo_preview(self, obj):
        if not obj or not obj.logo:
            return "-"
        from django.utils.html import format_html

        return format_html(
            '<img src="{}" style="width:42px;height:42px;object-fit:cover;border-radius:10px;border:1px solid #d1d5db;" />',
            obj.logo.url,
        )

    @admin.display(description="Start date", ordering="subscription__starts_on")
    def subscription_start(self, obj):
        subscription = getattr(obj, "subscription", None)
        return subscription.starts_on if subscription else None

    @admin.display(description="Plan", ordering="subscription__plan")
    def subscription_plan(self, obj):
        subscription = getattr(obj, "subscription", None)
        return subscription.get_plan_display() if subscription else None

    @admin.display(description="Expiry date", ordering="subscription__ends_on")
    def subscription_expiry(self, obj):
        subscription = getattr(obj, "subscription", None)
        return subscription.ends_on if subscription else None

    @admin.display(description="Account status", ordering="status")
    def effective_status(self, obj):
        subscription = getattr(obj, "subscription", None)
        if subscription and subscription.is_expired:
            return "Expired"
        return obj.get_status_display()

    @admin.display(description="Days remaining")
    def days_remaining(self, obj):
        subscription = getattr(obj, "subscription", None)
        if not subscription or not subscription.ends_on:
            return "-"
        remaining = (subscription.ends_on - timezone.localdate()).days
        return max(remaining, 0)

    @admin.display(description="Admin login")
    def admin_login(self, obj):
        profile = (
            obj.user_profiles.filter(role=UserProfile.Role.INSTITUTE_ADMIN)
            .select_related("user")
            .first()
        )
        if not profile:
            return "Not created"
        state = "Active" if profile.user.is_active else "Disabled"
        return f"{profile.user.username} ({state})"

    @admin.action(description="Activate selected schools")
    def activate_accounts(self, request, queryset):
        updated = queryset.update(status=Institute.Status.ACTIVE)
        self.message_user(request, f"{updated} school account(s) activated.")

    @admin.action(description="Move selected schools to Free Trial")
    def start_trials(self, request, queryset):
        updated = 0
        for institute in queryset:
            subscription, _created = InstituteSubscription.objects.get_or_create(
                institute=institute
            )
            subscription.plan = InstituteSubscription.Plan.FREE_TRIAL
            subscription.save(update_fields=("plan", "updated_at"))
            institute.status = Institute.Status.TRIAL
            institute.save(update_fields=("status", "updated_at"))
            updated += 1
        self.message_user(request, f"{updated} school account(s) moved to Free Trial.")

    @admin.action(description="Suspend selected schools")
    def suspend_accounts(self, request, queryset):
        updated = queryset.update(status=Institute.Status.SUSPENDED)
        self.message_user(request, f"{updated} school account(s) suspended.")


@admin.register(SubscriptionPayment)
class SubscriptionPaymentAdmin(admin.ModelAdmin):
    list_display = ("institute", "amount", "paid_on", "method", "transaction_id")
    list_filter = ("method", "paid_on")
    search_fields = ("institute__name", "institute__code", "transaction_id", "notes")
    autocomplete_fields = ("institute",)
    date_hierarchy = "paid_on"


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    extra = 0
    max_num = 1
    autocomplete_fields = ("institute",)


class SaaSUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "user_role",
        "profile_institute",
        "active_badge",
        "is_staff",
        "is_superuser",
        "date_joined",
        "last_login",
    )
    list_filter = UserAdmin.list_filter + (
        NonStudentInstituteFilter,
        "profile__role",
    )
    search_fields = UserAdmin.search_fields + (
        "profile__institute__name",
        "teacher_profile__institute__name",
        "profile__phone",
    )

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("profile__institute", "teacher_profile__institute")
            .exclude(student_profile__isnull=False)
            .exclude(profile__role=UserProfile.Role.STUDENT_PARENT)
            .distinct()
        )

    @admin.display(description="Role", ordering="profile__role")
    def user_role(self, obj):
        profile = getattr(obj, "profile", None)
        if profile:
            return profile.get_role_display()
        if getattr(obj, "teacher_profile", None):
            return "Teacher"
        if obj.is_superuser:
            return "Superuser"
        if obj.is_staff:
            return "Staff"
        return "-"

    @admin.display(description="Institute", ordering="profile__institute__name")
    def profile_institute(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and profile.institute_id:
            return profile.institute
        teacher_profile = getattr(obj, "teacher_profile", None)
        if teacher_profile and teacher_profile.institute_id:
            return teacher_profile.institute
        return "-"

    @admin.display(description="Active", ordering="is_active")
    def active_badge(self, obj):
        color = "#15803d" if obj.is_active else "#b91c1c"
        label = "Active" if obj.is_active else "Inactive"
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            color,
            label,
        )


admin.site.unregister(User)
admin.site.register(User, SaaSUserAdmin)
admin.site.unregister(Group)


_default_admin_get_urls = admin.site.get_urls
_default_admin_get_app_list = admin.site.get_app_list


def _ultracoachmatrix_admin_urls():
    return [
        path(
            "all-users-except-students/",
            admin.site.admin_view(all_non_student_users_view),
            name="all_non_student_users",
        ),
    ] + _default_admin_get_urls()


def _ultracoachmatrix_admin_app_list(request, app_label=None):
    app_list = _default_admin_get_app_list(request, app_label)
    if app_label not in (None, "super_admin"):
        return app_list
    for app in app_list:
        if app.get("app_label") == "super_admin":
            app["models"].append(
                {
                    "name": "All users except students",
                    "object_name": "AllNonStudentUsers",
                    "perms": {"view": True},
                    "admin_url": reverse("admin:all_non_student_users"),
                    "add_url": None,
                    "view_only": True,
                }
            )
            break
    return app_list


admin.site.get_urls = _ultracoachmatrix_admin_urls
admin.site.get_app_list = _ultracoachmatrix_admin_app_list


@admin.register(SupportTicket)
class SupportTicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "institute",
        "subject",
        "category",
        "priority",
        "status",
        "created_at",
    )
    list_filter = ("status", "priority", "category", "created_at")
    search_fields = ("institute__name", "subject", "message", "admin_response")
    readonly_fields = ("institute", "created_by", "created_at", "updated_at", "responded_at")
    fields = (
        "institute",
        "created_by",
        "category",
        "priority",
        "subject",
        "message",
        "status",
        "admin_response",
        "responded_at",
        "created_at",
        "updated_at",
    )

    def save_model(self, request, obj, form, change):
        response_changed = obj.admin_response and "admin_response" in form.changed_data
        if response_changed:
            obj.responded_at = timezone.now()
        super().save_model(request, obj, form, change)
