from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.utils import timezone

from super_admin.media_utils import expense_document_upload_path


class FeeCategory(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="fee_categories",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_categories",
    )
    name = models.CharField(max_length=120)
    default_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["institute", "academic_year", "name"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "is_active"], name="feecat_inst_year_idx"),
            models.Index(fields=["institute", "is_active", "name"], name="feecat_inst_active_idx"),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.academic_year_id and self.academic_year.institute_id != self.institute_id:
            raise ValidationError({"academic_year": "Selected academic session belongs to another institute."})

    def save(self, *args, **kwargs):
        if self.institute_id and not self.academic_year_id:
            from institute_admin.models import AcademicYear

            self.academic_year = (
                AcademicYear.objects.filter(
                    institute_id=self.institute_id,
                    start_date__lte=timezone.localdate(),
                    end_date__gte=timezone.localdate(),
                )
                .order_by("-start_date", "-pk")
                .first()
                or AcademicYear.objects.filter(institute_id=self.institute_id, is_active=True)
                .order_by("-start_date", "-pk")
                .first()
                or AcademicYear.objects.filter(institute_id=self.institute_id)
                .order_by("-start_date", "-pk")
                .first()
            )
        self.full_clean()
        super().save(*args, **kwargs)


class FeeInvoice(models.Model):
    class Status(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIAL = "PARTIAL", "Partial"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    student = models.ForeignKey(
        "student_parent.StudentProfile",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    academic_session = models.ForeignKey(
        "student_parent.StudentAcademicSession",
        on_delete=models.CASCADE,
        related_name="fee_invoices",
    )
    enrollment = models.ForeignKey(
        "student_parent.StudentEnrollment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    course = models.ForeignKey(
        "institute_admin.Course",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    batch = models.ForeignKey(
        "institute_admin.Batch",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_invoices",
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    title = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-due_date"]
        indexes = [
            models.Index(fields=["academic_session", "status", "-due_date"], name="inv_session_status_idx"),
            models.Index(fields=["academic_session", "-due_date"], name="inv_session_due_idx"),
            models.Index(fields=["student", "status", "-due_date"], name="inv_student_status_idx"),
            models.Index(fields=["institute", "status", "-due_date"], name="inv_inst_status_idx"),
            models.Index(fields=["enrollment", "status"], name="inv_enroll_status_idx"),
        ]

    def __str__(self):
        return f"{self.student} - {self.title}"

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_session_id:
            session_institute_id = self.academic_session.institute_id
            if self.institute_id and self.institute_id != session_institute_id:
                errors["institute"] = "Invoice institute must match the academic session institute."
            if self.student_id and self.student_id != self.academic_session.student_id:
                errors["student"] = "Invoice student must match the academic session student."
            if self.enrollment_id and self.enrollment.academic_session_id != self.academic_session_id:
                errors["enrollment"] = "Selected enrollment belongs to another academic session."
            if self.course_id and self.course.institute_id != session_institute_id:
                errors["course"] = "Selected course belongs to another institute."
            if self.batch_id and self.batch.institute_id != session_institute_id:
                errors["batch"] = "Selected batch belongs to another institute."
            if self.category_id and self.category.institute_id != session_institute_id:
                errors["category"] = "Selected fee category belongs to another institute."
            if self.category_id and self.category.academic_year_id != self.academic_session.academic_year_id:
                errors["category"] = "Selected fee category belongs to another academic year."
            if self.course_id and self.course.academic_year_id != self.academic_session.academic_year_id:
                errors["course"] = "Selected course belongs to another academic year."
            if self.batch_id and self.batch.academic_year_id != self.academic_session.academic_year_id:
                errors["batch"] = "Selected batch belongs to another academic year."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.academic_session_id:
            self.student = self.academic_session.student
            self.institute = self.academic_session.institute
        if self.enrollment_id and self.enrollment.academic_session_id != self.academic_session_id:
            self.academic_session = self.enrollment.academic_session
            self.student = self.academic_session.student
            self.institute = self.academic_session.institute
        self.full_clean()
        super().save(*args, **kwargs)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        UPI = "UPI", "UPI"
        CARD = "CARD", "Card"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        VOIDED = "VOIDED", "Voided"

    invoice = models.ForeignKey(FeeInvoice, on_delete=models.CASCADE, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_on = models.DateField()
    method = models.CharField(max_length=30, choices=Method.choices, default=Method.CASH)
    received_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="received_payments",
    )
    receipt_number = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(default=timezone.now)
    voided_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="voided_payments",
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-paid_on"]
        indexes = [
            models.Index(fields=["invoice", "status", "-paid_on"], name="pay_invoice_status_idx"),
            models.Index(fields=["status", "-paid_on"], name="pay_status_date_idx"),
            models.Index(fields=["status", "-created_at", "-id"], name="pay_status_created_idx"),
            models.Index(fields=["receipt_number"], name="pay_receipt_idx"),
        ]

    def __str__(self):
        return f"{self.invoice} - {self.amount}"

    def void(self, user, reason):
        self.status = self.Status.VOIDED
        self.voided_by = user
        self.voided_at = timezone.now()
        self.void_reason = reason
        self.save(update_fields=["status", "voided_by", "voided_at", "void_reason"])


class PaymentActivity(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        VOIDED = "VOIDED", "Voided"

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="activities")
    action = models.CharField(max_length=20, choices=Action.choices)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payment_activities",
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_method = models.CharField(max_length=30, blank=True)
    new_method = models.CharField(max_length=30, blank=True)
    old_receipt_number = models.CharField(max_length=60, blank=True)
    new_receipt_number = models.CharField(max_length=60, blank=True)
    note = models.CharField(max_length=255)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [
            models.Index(fields=["payment", "-performed_at"], name="payact_payment_time_idx"),
        ]

    def __str__(self):
        return f"{self.payment} - {self.get_action_display()}"


class Expense(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="expenses",
    )
    title = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    spent_on = models.DateField()
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_expenses",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-spent_on"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "-spent_on"], name="expense_inst_year_idx"),
            models.Index(fields=["institute", "-spent_on"], name="expense_inst_date_idx"),
        ]

    def __str__(self):
        return f"{self.title} - {self.amount}"

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_year_id and self.academic_year.institute_id != self.institute_id:
            errors["academic_year"] = "Selected academic session belongs to another institute."
        if self.academic_year_id and self.spent_on:
            if not (self.academic_year.start_date <= self.spent_on <= self.academic_year.end_date):
                errors["spent_on"] = "Expense date must be inside the selected academic session."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.institute_id and not self.academic_year_id:
            from institute_admin.models import AcademicYear

            reference_date = self.spent_on or timezone.localdate()
            self.academic_year = (
                AcademicYear.objects.filter(
                    institute_id=self.institute_id,
                    start_date__lte=reference_date,
                    end_date__gte=reference_date,
                )
                .order_by("-start_date", "-pk")
                .first()
                or AcademicYear.objects.filter(institute_id=self.institute_id, is_active=True)
                .order_by("-start_date", "-pk")
                .first()
                or AcademicYear.objects.filter(institute_id=self.institute_id)
                .order_by("-start_date", "-pk")
                .first()
            )
        self.full_clean()
        super().save(*args, **kwargs)


class ExpenseBin(models.Model):
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="expense_bin_records",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expense_bin_records",
    )
    original_expense_id = models.PositiveIntegerField()
    title = models.CharField(max_length=160)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    spent_on = models.DateField()
    recorded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_deleted_expenses",
    )
    deleted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="deleted_expenses",
    )
    deleted_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-deleted_at"]
        indexes = [
            models.Index(fields=["institute", "academic_year", "-deleted_at"], name="expbin_inst_year_time_idx"),
            models.Index(fields=["original_expense_id"], name="expbin_original_idx"),
        ]

    def __str__(self):
        return f"{self.title} - {self.amount}"

    def can_be_deleted_by(self, user):
        profile = getattr(user, "profile", None)
        return bool(profile and profile.role == "INSTITUTE_ADMIN" and profile.institute_id == self.institute_id)

    def delete_permanently(self, user):
        if not self.can_be_deleted_by(user):
            raise PermissionDenied("Only institute admins can delete expense bin records.")
        return super().delete()


class ExpenseActivity(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        UPDATED = "UPDATED", "Updated"
        DELETED = "DELETED", "Deleted"

    expense = models.ForeignKey(
        Expense,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    expense_bin = models.ForeignKey(
        ExpenseBin,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
    )
    institute = models.ForeignKey(
        "super_admin.Institute",
        on_delete=models.CASCADE,
        related_name="expense_activities",
    )
    academic_year = models.ForeignKey(
        "institute_admin.AcademicYear",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expense_activities",
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="expense_activities",
    )
    performed_at = models.DateTimeField(auto_now_add=True)
    old_title = models.CharField(max_length=160, blank=True)
    new_title = models.CharField(max_length=160, blank=True)
    old_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    new_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    old_spent_on = models.DateField(null=True, blank=True)
    new_spent_on = models.DateField(null=True, blank=True)
    old_note = models.CharField(max_length=255, blank=True)
    new_note = models.CharField(max_length=255, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-performed_at"]
        indexes = [
            models.Index(fields=["expense", "-performed_at"], name="expact_expense_time_idx"),
            models.Index(fields=["institute", "academic_year", "-performed_at"], name="expact_inst_year_time_idx"),
            models.Index(fields=["action", "-performed_at"], name="expact_action_time_idx"),
        ]

    def __str__(self):
        title = self.new_title or self.old_title or self.snapshot.get("title") or "Expense"
        return f"{title} - {self.get_action_display()}"


class ExpenseDocument(models.Model):
    expense = models.ForeignKey(
        Expense,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    file = models.FileField(upload_to=expense_document_upload_path)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["expense", "-uploaded_at"], name="expdoc_expense_time_idx"),
        ]

    def __str__(self):
        return self.file_name

    @property
    def file_name(self):
        return self.file.name.rsplit("/", 1)[-1] if self.file else "Document"
