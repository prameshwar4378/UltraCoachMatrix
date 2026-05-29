from django.contrib import admin

from .models import Attendance, Exam, ExamResult, Homework, HomeworkAttachment, TeacherProfile


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "institute", "employee_id", "teacher_type", "specialization", "joined_on", "is_active")
    list_filter = ("institute", "teacher_type", "is_active")
    search_fields = (
        "user__username",
        "user__first_name",
        "user__last_name",
        "employee_id",
        "specialization",
    )


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("academic_session", "student", "batch", "date", "status", "marked_by")
    list_filter = ("academic_session__academic_year", "batch", "status", "date")
    search_fields = ("academic_session__admission_number", "student__user__username")


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ("title", "batch", "course", "due_date", "created_by", "created_at")
    list_filter = ("batch", "course", "due_date", "created_at")
    search_fields = ("title", "instructions")


@admin.register(HomeworkAttachment)
class HomeworkAttachmentAdmin(admin.ModelAdmin):
    list_display = ("homework", "file", "uploaded_at")
    search_fields = ("homework__title", "file")


class ExamResultInline(admin.TabularInline):
    model = ExamResult
    extra = 0


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("title", "batch", "exam_date", "total_marks", "created_by")
    list_filter = ("batch", "exam_date")
    search_fields = ("title", "batch__name")
    inlines = [ExamResultInline]


@admin.register(ExamResult)
class ExamResultAdmin(admin.ModelAdmin):
    list_display = ("exam", "student", "marks_obtained")
    list_filter = ("exam",)
    search_fields = ("student__academic_sessions__admission_number", "student__user__username", "exam__title")
