from django.contrib import admin

from .models import (
    Institute,
    InstituteSubscription,
    SubscriptionPlan,
    UserProfile,
)


@admin.register(Institute)
class InstituteAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "owner_name", "phone", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("name", "code", "owner_name", "phone", "email")
    prepopulated_fields = {"code": ("name",)}


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "institute", "phone")
    list_filter = ("role", "institute")
    search_fields = ("user__username", "user__first_name", "user__last_name", "phone")


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "monthly_price", "max_students", "max_teachers", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(InstituteSubscription)
class InstituteSubscriptionAdmin(admin.ModelAdmin):
    list_display = ("institute", "plan", "status", "starts_on", "ends_on")
    list_filter = ("status", "plan")
    search_fields = ("institute__name", "plan__name")
