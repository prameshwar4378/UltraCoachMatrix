from django.contrib import admin

from .models import AcademicYear, Batch, Course, Notice, NoticeRead


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "start_date", "end_date", "is_active")
    list_filter = ("institute", "is_active")
    search_fields = ("name", "institute__name")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "academic_year", "duration", "fee_amount", "is_active")
    list_filter = ("institute", "academic_year", "is_active")
    search_fields = ("name", "description")


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "academic_year", "timing", "total_course_fee", "is_active", "start_date")
    list_filter = ("institute", "academic_year", "courses", "is_active")
    search_fields = ("name", "courses__name")
    filter_horizontal = ("courses", "teachers")


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ("title", "institute", "audience", "category", "priority", "is_published", "push_to_app", "created_by", "created_at")
    list_filter = ("institute", "audience", "category", "priority", "is_published", "push_to_app", "created_at")
    search_fields = ("title", "message")
    filter_horizontal = ("target_batches", "target_courses", "target_students")


@admin.register(NoticeRead)
class NoticeReadAdmin(admin.ModelAdmin):
    list_display = ("notice", "user", "read_at")
    list_filter = ("read_at", "notice__institute")
    search_fields = ("notice__title", "user__username", "user__first_name", "user__last_name")
