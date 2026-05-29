from django.contrib import admin

from .models import (
    GuardianProfile,
    PushNotification,
    StudentAcademicSession,
    StudentDocument,
    StudentEnrollment,
    StudentProfile,
    UserDevice,
)


class GuardianInline(admin.TabularInline):
    model = GuardianProfile
    extra = 0


class StudentDocumentInline(admin.TabularInline):
    model = StudentDocument
    extra = 0


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "user", "institute", "current_school_name", "is_active")
    list_filter = ("institute", "is_active")
    search_fields = (
        "admission_number",
        "user__username",
        "user__first_name",
        "user__last_name",
        "guardians__name",
        "guardians__phone",
    )
    inlines = [GuardianInline, StudentDocumentInline]


@admin.register(StudentAcademicSession)
class StudentAcademicSessionAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "student", "academic_year", "institute", "status", "joined_on")
    list_filter = ("institute", "academic_year", "status")
    search_fields = (
        "admission_number",
        "student__admission_number",
        "student__user__username",
        "student__user__first_name",
        "student__user__last_name",
    )


@admin.register(GuardianProfile)
class GuardianProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "student", "relation", "phone", "is_primary")
    list_filter = ("is_primary", "relation")
    search_fields = ("name", "phone", "email", "student__admission_number")


@admin.register(StudentEnrollment)
class StudentEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("academic_session", "student", "batch", "status", "enrolled_on", "custom_fee_amount")
    list_filter = ("academic_session__academic_year", "batch", "status", "enrolled_on")
    search_fields = ("academic_session__admission_number", "student__user__username", "batch__name")
    filter_horizontal = ("courses",)


@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ("student", "document_type", "title", "uploaded_at")
    list_filter = ("document_type", "uploaded_at")
    search_fields = ("student__academic_sessions__admission_number", "student__user__username", "title")


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "device_id", "is_active", "last_seen_at")
    list_filter = ("platform", "is_active", "last_seen_at")
    search_fields = ("user__username", "user__first_name", "user__last_name", "token", "device_id")


@admin.register(PushNotification)
class PushNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "notification_type", "title", "status", "created_at", "sent_at")
    list_filter = ("notification_type", "status", "created_at")
    search_fields = ("user__username", "title", "body", "firebase_message_id", "error_message")
    readonly_fields = ("created_at", "sent_at")
