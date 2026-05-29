from django.contrib.auth.models import User
from django.db import models
from decimal import Decimal


class AcademicYear(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="academic_years",
    )
    name = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date"]
        unique_together = ["institute", "name"]

    def __str__(self):
        return f"{self.institute} - {self.name}"


class Course(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="courses",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="courses",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    duration = models.CharField(max_length=80, blank=True)
    fee_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["academic_year__start_date", "name"]
        unique_together = ["institute", "academic_year", "name"]

    def __str__(self):
        return self.name


class Batch(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="batches",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="batches",
    )
    courses = models.ManyToManyField(Course, related_name="batches")
    name = models.CharField(max_length=120)
    teachers = models.ManyToManyField(User, blank=True, related_name="assigned_batches")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    timing = models.CharField(max_length=120, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["academic_year__start_date", "name"]
        unique_together = ["institute", "academic_year", "name"]

    def __str__(self):
        return self.name

    @property
    def total_course_fee(self):
        return sum((course.fee_amount for course in self.courses.all()), Decimal("0.00"))


class Notice(models.Model):
    class Audience(models.TextChoices):
        EVERYONE = "EVERYONE", "Everyone"
        TEACHERS = "TEACHERS", "Teachers"
        STUDENTS_PARENTS = "STUDENTS_PARENTS", "Students/Parents"

    class Category(models.TextChoices):
        GENERAL = "GENERAL", "General"
        ACADEMIC = "ACADEMIC", "Academic"
        FEES = "FEES", "Fees"
        EXAM = "EXAM", "Exam"
        EVENT = "EVENT", "Event"
        HOLIDAY = "HOLIDAY", "Holiday"
        URGENT = "URGENT", "Urgent"

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        IMPORTANT = "IMPORTANT", "Important"
        URGENT = "URGENT", "Urgent"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="notices",
    )
    title = models.CharField(max_length=160)
    message = models.TextField()
    audience = models.CharField(max_length=30, choices=Audience.choices, default=Audience.EVERYONE)
    category = models.CharField(max_length=30, choices=Category.choices, default=Category.GENERAL)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.NORMAL)
    target_batches = models.ManyToManyField(Batch, blank=True, related_name="notices")
    target_courses = models.ManyToManyField(Course, blank=True, related_name="notices")
    target_students = models.ManyToManyField(
        "student_parent.StudentProfile",
        blank=True,
        related_name="notices",
    )
    publish_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    push_to_app = models.BooleanField(default=True)
    pin_on_top = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_notices",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=True)

    class Meta:
        ordering = ["-pin_on_top", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_active_for_app(self):
        from django.utils import timezone

        now = timezone.now()
        if not self.is_published:
            return False
        if self.publish_at and self.publish_at > now:
            return False
        if self.expires_at and self.expires_at < now:
            return False
        return True

    @classmethod
    def active_for_app(cls):
        from django.db.models import Q
        from django.utils import timezone

        now = timezone.now()
        return cls.objects.filter(is_published=True, push_to_app=True).filter(
            Q(publish_at__isnull=True) | Q(publish_at__lte=now),
            Q(expires_at__isnull=True) | Q(expires_at__gte=now),
        )

    @classmethod
    def for_student(cls, student):
        from django.db.models import Q
        from student_parent.models import StudentEnrollment

        enrollments = StudentEnrollment.objects.filter(student=student)
        batch_ids = enrollments.values_list("batch_id", flat=True)
        course_ids = enrollments.values_list("courses__id", flat=True)
        audience_filter = Q(audience=cls.Audience.EVERYONE) | Q(audience=cls.Audience.STUDENTS_PARENTS)
        target_filter = (
            Q(target_batches__isnull=True, target_courses__isnull=True, target_students__isnull=True)
            | Q(target_batches__in=batch_ids)
            | Q(target_courses__in=course_ids)
            | Q(target_students=student)
        )
        return cls.active_for_app().filter(institute=student.institute).filter(audience_filter).filter(target_filter).distinct()


class NoticeRead(models.Model):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="read_receipts")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notice_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-read_at"]
        unique_together = ["notice", "user"]

    def __str__(self):
        return f"{self.notice} read by {self.user}"
