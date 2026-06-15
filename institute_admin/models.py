from django.contrib.auth.models import User
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone
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
        indexes = [
            models.Index(fields=["institute", "is_active", "-start_date"], name="ay_inst_active_idx"),
        ]

    def __str__(self):
        return f"{self.institute} - {self.name}"


class BackgroundJob(models.Model):
    class JobType(models.TextChoices):
        STUDENT_IMPORT = "STUDENT_IMPORT", "Student import"
        FEE_NOTIFICATION = "FEE_NOTIFICATION", "Fee notification"
        NOTICE_NOTIFICATION = "NOTICE_NOTIFICATION", "Notice notification"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        FAILED = "FAILED", "Failed"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="background_jobs",
        null=True,
        blank=True,
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.SET_NULL,
        related_name="background_jobs",
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="background_jobs",
        null=True,
        blank=True,
    )
    job_type = models.CharField(max_length=40, choices=JobType.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    input_file = models.FileField(upload_to="background_jobs/input/", blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="bgjob_status_created_idx"),
            models.Index(fields=["institute", "job_type", "status"], name="bgjob_inst_type_idx"),
        ]

    def __str__(self):
        return f"{self.get_job_type_display()} - {self.get_status_display()}"


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
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="course_inst_year_idx"),
        ]

    def __str__(self):
        return self.name


class Subject(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="subjects",
    )
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.PROTECT,
        related_name="subjects",
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["academic_year__start_date", "name"]
        unique_together = ["institute", "academic_year", "name"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="subject_inst_year_idx"),
        ]

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
    weekly_timetable = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["academic_year__start_date", "name"]
        unique_together = ["institute", "academic_year", "name"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="batch_inst_year_idx"),
        ]

    def __str__(self):
        return self.name

    @property
    def total_course_fee(self):
        return sum((course.fee_amount for course in self.courses.all()), Decimal("0.00"))


class Lead(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        CONTACTED = "CONTACTED", "Contacted"
        FOLLOW_UP = "FOLLOW_UP", "Follow Up"
        CONVERTED = "CONVERTED", "Converted"
        CLOSED = "CLOSED", "Closed"

    class Source(models.TextChoices):
        WALK_IN = "WALK_IN", "Walk In"
        PHONE = "PHONE", "Phone"
        WEBSITE = "WEBSITE", "Website"
        REFERRAL = "REFERRAL", "Referral"
        OTHER = "OTHER", "Other"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="leads",
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    mobile_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.WALK_IN,
    )
    interested_class = models.ForeignKey(
        Course,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    interested_batch = models.ForeignKey(
        Batch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leads",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    follow_up_on = models.DateField(null=True, blank=True)
    message = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_leads",
    )
    converted_student = models.OneToOneField(
        "student_parent.StudentProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="converted_from_lead",
    )
    converted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["institute", "status", "-created_at"],
                name="lead_inst_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.full_name} - {self.mobile_number}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()


def default_visitor_entry_time():
    return timezone.localtime().time().replace(second=0, microsecond=0)


class Visitor(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="visitors",
    )
    visitor_name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=20)
    id_card_number = models.CharField("ID Card / Pass No", max_length=100, blank=True)
    meeting_with = models.CharField(max_length=200)
    total_person = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    visit_date = models.DateField(default=timezone.localdate)
    entry_time = models.TimeField(default=default_visitor_entry_time)
    exit_time = models.TimeField(null=True, blank=True)
    purpose = models.TextField("Purpose of Visit", blank=True)
    attachment = models.FileField(
        "Attachment / ID Scan",
        upload_to="visitors/id_scans/",
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_visitors",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-visit_date", "-entry_time", "-created_at"]
        indexes = [
            models.Index(
                fields=["institute", "-visit_date", "-entry_time"],
                name="visitor_inst_visit_idx",
            ),
        ]

    def __str__(self):
        return f"{self.visitor_name} - {self.phone_number}"


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
    push_notification_queued_at = models.DateTimeField(null=True, blank=True)
    push_notification_version = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["-pin_on_top", "-created_at"]
        indexes = [
            models.Index(fields=["institute", "is_published", "push_to_app", "-pin_on_top", "-created_at"], name="notice_app_feed_idx"),
            models.Index(fields=["institute", "category", "-created_at"], name="notice_category_idx"),
            models.Index(fields=["institute", "priority", "-created_at"], name="notice_priority_idx"),
            models.Index(
                fields=["is_published", "push_to_app", "push_notification_queued_at", "publish_at"],
                name="notice_push_due_idx",
            ),
        ]

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
    def for_student(cls, student, academic_session_id=None):
        from django.db.models import Q
        from student_parent.models import StudentEnrollment

        enrollments = StudentEnrollment.objects.filter(student=student)
        if academic_session_id:
            enrollments = enrollments.filter(academic_session_id=academic_session_id)
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

    @classmethod
    def for_teacher(cls, user, academic_year_id=None):
        from django.db.models import Q
        from django.utils import timezone

        profile = getattr(user, "profile", None)
        if not profile or not profile.institute_id:
            return cls.objects.none()

        batches = Batch.objects.filter(
            institute_id=profile.institute_id,
            teachers=user,
            is_active=True,
        )
        if academic_year_id:
            batches = batches.filter(academic_year_id=academic_year_id)
        batch_ids = batches.values_list("pk", flat=True)
        course_ids = Course.objects.filter(batches__in=batches).values_list("pk", flat=True)
        audience_filter = Q(audience=cls.Audience.EVERYONE) | Q(audience=cls.Audience.TEACHERS)
        target_filter = (
            Q(target_batches__isnull=True, target_courses__isnull=True, target_students__isnull=True)
            | Q(target_batches__in=batch_ids)
            | Q(target_courses__in=course_ids)
        )
        now = timezone.now()
        return (
            cls.objects.filter(is_published=True)
            .filter(Q(publish_at__isnull=True) | Q(publish_at__lte=now))
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gte=now))
            .filter(institute_id=profile.institute_id)
            .filter(audience_filter)
            .filter(target_filter)
            .distinct()
        )


class NoticeRead(models.Model):
    notice = models.ForeignKey(Notice, on_delete=models.CASCADE, related_name="read_receipts")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notice_reads")
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-read_at"]
        unique_together = ["notice", "user"]
        indexes = [
            models.Index(fields=["user", "-read_at"], name="notice_read_user_idx"),
        ]

    def __str__(self):
        return f"{self.notice} read by {self.user}"


class SupportTicket(models.Model):
    class Category(models.TextChoices):
        ACCOUNT = "ACCOUNT", "Account and login"
        BILLING = "BILLING", "Subscription and billing"
        SETUP = "SETUP", "Institute setup"
        STUDENTS = "STUDENTS", "Students and admissions"
        FEES = "FEES", "Fees and payments"
        ATTENDANCE = "ATTENDANCE", "Attendance"
        EXAMS = "EXAMS", "Exams and results"
        TECHNICAL = "TECHNICAL", "Technical issue"
        OTHER = "OTHER", "Other"

    class Priority(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        URGENT = "URGENT", "Urgent"

    class Status(models.TextChoices):
        NEW = "NEW", "New"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        RESOLVED = "RESOLVED", "Resolved"
        CLOSED = "CLOSED", "Closed"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="support_tickets",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_support_tickets",
    )
    category = models.CharField(max_length=30, choices=Category.choices)
    priority = models.CharField(
        max_length=20,
        choices=Priority.choices,
        default=Priority.NORMAL,
    )
    subject = models.CharField(max_length=160)
    message = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    admin_response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["institute", "status", "-created_at"],
                name="support_inst_status_idx",
            ),
        ]

    def __str__(self):
        return f"#{self.pk} {self.institute} - {self.subject}"
