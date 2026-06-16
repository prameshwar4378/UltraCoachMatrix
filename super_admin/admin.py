from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, User
from django.db.models import Q
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
            {"fields": ("name", "code", "logo", "logo_preview", "owner_name", "phone", "email", "address")},
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
        "profile_institute",
        "is_active",
        "date_joined",
    )
    list_filter = UserAdmin.list_filter + ("profile__institute",)
    search_fields = UserAdmin.search_fields + ("profile__institute__name", "profile__phone")

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .filter(
                Q(is_superuser=True)
                | Q(profile__role=UserProfile.Role.SUPER_ADMIN)
                | Q(profile__role=UserProfile.Role.INSTITUTE_ADMIN)
            )
            .distinct()
        )

    @admin.display(description="Institute", ordering="profile__institute__name")
    def profile_institute(self, obj):
        profile = getattr(obj, "profile", None)
        return profile.institute if profile else "-"


admin.site.unregister(User)
admin.site.register(User, SaaSUserAdmin)
admin.site.unregister(Group)


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
