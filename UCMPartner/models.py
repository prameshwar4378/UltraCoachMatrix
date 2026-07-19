from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class PartnerProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        BLOCKED = "BLOCKED", "Blocked"

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="ucm_partner_profile",
    )
    full_name = models.CharField(max_length=120)
    mobile = models.CharField(max_length=20, unique=True)
    email = models.EmailField(blank=True)
    area = models.CharField(max_length=120, blank=True)
    bank_account_holder_name = models.CharField(max_length=120, blank=True)
    bank_name = models.CharField(max_length=120, blank=True)
    bank_account_number = models.CharField(max_length=40, blank=True)
    bank_ifsc_code = models.CharField(max_length=20, blank=True)
    phonepe_number = models.CharField(max_length=20, blank=True)
    google_pay_number = models.CharField(max_length=20, blank=True)
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    notes = models.TextField(blank=True)
    joined_on = models.DateField(default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            models.Index(fields=["status", "area"], name="partner_status_area_idx"),
        ]

    def __str__(self):
        return self.full_name


class PartnerLead(models.Model):
    class Status(models.TextChoices):
        NEW = "NEW", "New"
        FOLLOW_UP = "FOLLOW_UP", "Follow-up"
        CONVERTED = "CONVERTED", "Converted"
        REJECTED = "REJECTED", "Rejected"

    class Priority(models.TextChoices):
        HOT = "HOT", "Hot"
        WARM = "WARM", "Warm"
        COLD = "COLD", "Cold"

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name="leads",
    )
    school_name = models.CharField(max_length=160)
    contact_person = models.CharField(max_length=120, blank=True)
    mobile = models.CharField(max_length=20)
    city = models.CharField(max_length=80, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
    )
    priority = models.CharField(
        max_length=10,
        choices=Priority.choices,
        default=Priority.WARM,
    )
    next_follow_up_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["partner", "status"], name="lead_partner_status_idx"),
            models.Index(fields=["partner", "priority"], name="lead_partner_priority_idx"),
            models.Index(fields=["next_follow_up_on"], name="lead_followup_idx"),
        ]

    def __str__(self):
        return self.school_name


class PartnerCommission(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name="commissions",
    )
    lead = models.OneToOneField(
        PartnerLead,
        on_delete=models.PROTECT,
        related_name="commission",
    )
    sale_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("20.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    sale_date = models.DateField(default=timezone.localdate)
    paid_on = models.DateField(null=True, blank=True)
    transaction_id = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-sale_date", "-created_at"]
        indexes = [
            models.Index(fields=["partner", "status"], name="comm_partner_status_idx"),
            models.Index(fields=["sale_date"], name="comm_sale_date_idx"),
        ]

    def __str__(self):
        return f"{self.partner} - {self.commission_amount}"

    def clean(self):
        super().clean()
        if self.lead_id and self.partner_id and self.lead.partner_id != self.partner_id:
            raise ValidationError({"lead": "Selected lead belongs to another partner."})
        if self.status == self.Status.PAID and not self.paid_on:
            raise ValidationError({"paid_on": "Paid date is required when commission is paid."})

    def save(self, *args, **kwargs):
        self.commission_amount = (
            self.sale_amount * self.commission_percent / Decimal("100.00")
        ).quantize(Decimal("0.01"))
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"commission_amount"}
        self.full_clean()
        super().save(*args, **kwargs)


class PartnerCallHistory(models.Model):
    class Result(models.TextChoices):
        CONNECTED = "CONNECTED", "Connected"
        NOT_CONNECTED = "NOT_CONNECTED", "Not connected"
        INTERESTED = "INTERESTED", "Interested"
        NOT_INTERESTED = "NOT_INTERESTED", "Not interested"
        CALL_LATER = "CALL_LATER", "Call later"

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name="call_history",
    )
    lead = models.ForeignKey(
        PartnerLead,
        on_delete=models.CASCADE,
        related_name="call_history",
    )
    call_time = models.DateTimeField(default=timezone.now)
    result = models.CharField(max_length=30, choices=Result.choices)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-call_time", "-created_at"]
        indexes = [
            models.Index(fields=["partner", "-call_time"], name="call_partner_time_idx"),
            models.Index(fields=["lead", "-call_time"], name="call_lead_time_idx"),
        ]
        verbose_name = "Partner call history"
        verbose_name_plural = "Partner call history"

    def __str__(self):
        return f"{self.lead} - {self.get_result_display()}"

    def clean(self):
        super().clean()
        if self.lead_id and self.partner_id and self.lead.partner_id != self.partner_id:
            raise ValidationError({"lead": "Selected lead belongs to another partner."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class PartnerSaleClaim(models.Model):
    class Status(models.TextChoices):
        PENDING_REVIEW = "PENDING_REVIEW", "Pending review"
        APPROVED = "APPROVED", "Approved"
        PAID = "PAID", "Paid"
        REJECTED = "REJECTED", "Rejected"

    partner = models.ForeignKey(
        PartnerProfile,
        on_delete=models.CASCADE,
        related_name="sale_claims",
    )
    lead = models.OneToOneField(
        PartnerLead,
        on_delete=models.PROTECT,
        related_name="sale_claim",
    )
    selling_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    commission_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("100.00")),
        ],
    )
    commission_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        editable=False,
    )
    payment_screenshot = models.ImageField(
        upload_to="partner_sale_claims/screenshots/",
    )
    payment_note = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING_REVIEW,
    )
    admin_note = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["partner", "status"], name="claim_partner_status_idx"),
            models.Index(fields=["submitted_at"], name="claim_submitted_idx"),
        ]

    def __str__(self):
        return f"{self.lead} - {self.get_status_display()}"

    def clean(self):
        super().clean()
        if self.lead_id and self.partner_id and self.lead.partner_id != self.partner_id:
            raise ValidationError({"lead": "Selected lead belongs to another partner."})
        if self.lead_id and self.lead.status != PartnerLead.Status.CONVERTED:
            raise ValidationError({"lead": "Sale claim is allowed only for converted leads."})

    def save(self, *args, **kwargs):
        if self.partner_id and self.commission_percent == Decimal("0.00"):
            self.commission_percent = self.partner.commission_percent
        self.commission_amount = (
            self.selling_price * self.commission_percent / Decimal("100.00")
        ).quantize(Decimal("0.01"))
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"commission_amount"}
        now = timezone.now()
        if self.status == self.Status.APPROVED and self.approved_at is None:
            self.approved_at = now
        if self.status == self.Status.PAID:
            if self.approved_at is None:
                self.approved_at = now
            if self.paid_at is None:
                self.paid_at = now
        self.full_clean()
        super().save(*args, **kwargs)
        self.sync_commission_record()

    def sync_commission_record(self):
        commission_status = PartnerCommission.Status.PENDING
        paid_on = None
        if self.status == self.Status.PAID:
            commission_status = PartnerCommission.Status.PAID
            paid_on = (self.paid_at or timezone.now()).date()
        elif self.status == self.Status.REJECTED:
            commission_status = PartnerCommission.Status.CANCELLED

        existing_commission = PartnerCommission.objects.filter(lead=self.lead).first()
        sale_date = (
            existing_commission.sale_date
            if existing_commission is not None
            else self.submitted_at.date()
            if self.submitted_at
            else timezone.localdate()
        )

        PartnerCommission.objects.update_or_create(
            lead=self.lead,
            defaults={
                "partner": self.partner,
                "sale_amount": self.selling_price,
                "commission_percent": self.commission_percent,
                "status": commission_status,
                "sale_date": sale_date,
                "paid_on": paid_on,
                "notes": f"Managed from sale claim #{self.pk}. {self.payment_note}".strip(),
            },
        )
