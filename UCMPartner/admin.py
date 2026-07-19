from datetime import datetime, time
from urllib.parse import urlencode

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils import timezone

from .models import (
    PartnerCallHistory,
    PartnerCommission,
    PartnerLead,
    PartnerProfile,
    PartnerSaleClaim,
)


@admin.register(PartnerProfile)
class PartnerProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "username",
        "mobile",
        "email",
        "area",
        "phonepe_number",
        "google_pay_number",
        "commission_percent",
        "status",
        "joined_on",
    )
    list_filter = ("status", "area", "joined_on")
    list_editable = ("status",)
    search_fields = (
        "full_name",
        "mobile",
        "email",
        "area",
        "phonepe_number",
        "google_pay_number",
        "bank_name",
        "bank_account_number",
        "user__username",
    )
    autocomplete_fields = ("user",)
    date_hierarchy = "joined_on"
    ordering = ("full_name",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Login and identity",
            {
                "fields": (
                    "user",
                    "full_name",
                    "mobile",
                    "email",
                )
            },
        ),
        (
            "Partner setup",
            {
                "fields": (
                    "area",
                    "commission_percent",
                    "status",
                    "joined_on",
                    "notes",
                )
            },
        ),
        (
            "Bank and payout details",
            {
                "fields": (
                    "bank_account_holder_name",
                    "bank_name",
                    "bank_account_number",
                    "bank_ifsc_code",
                    "phonepe_number",
                    "google_pay_number",
                )
            },
        ),
        (
            "System",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description="Username")
    def username(self, obj):
        return obj.user.get_username()


@admin.register(PartnerLead)
class PartnerLeadAdmin(admin.ModelAdmin):
    list_display = (
        "school_name",
        "partner",
        "contact_person",
        "mobile",
        "city",
        "status",
        "priority",
        "next_follow_up_on",
        "updated_at",
    )
    list_filter = ("status", "priority", "city", "partner", "next_follow_up_on", "created_at")
    list_editable = ("status", "priority", "next_follow_up_on")
    search_fields = (
        "school_name",
        "contact_person",
        "mobile",
        "city",
        "partner__full_name",
        "partner__mobile",
        "partner__user__username",
    )
    autocomplete_fields = ("partner",)
    date_hierarchy = "next_follow_up_on"
    ordering = ("-updated_at",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Lead",
            {
                "fields": (
                    "partner",
                    "school_name",
                    "contact_person",
                    "mobile",
                    "city",
                )
            },
        ),
        (
            "Follow-up",
            {
                "fields": (
                    "status",
                    "priority",
                    "next_follow_up_on",
                    "notes",
                )
            },
        ),
        (
            "System",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("partner", "partner__user")


@admin.register(PartnerCommission)
class PartnerCommissionAdmin(admin.ModelAdmin):
    list_display = (
        "partner",
        "lead",
        "sale_amount",
        "commission_percent",
        "commission_amount",
        "status",
        "sale_date",
        "paid_on",
        "transaction_id",
    )
    list_filter = ("status", "partner", "sale_date", "paid_on")
    list_editable = ("status", "paid_on")
    search_fields = (
        "partner__full_name",
        "partner__mobile",
        "partner__user__username",
        "lead__school_name",
        "lead__mobile",
        "lead__city",
    )
    autocomplete_fields = ("partner", "lead")
    date_hierarchy = "sale_date"
    ordering = ("-sale_date", "-created_at")
    readonly_fields = ("commission_amount", "created_at", "updated_at")
    actions = ("mark_selected_as_paid",)
    fieldsets = (
        (
            "Sale",
            {
                "fields": (
                    "partner",
                    "lead",
                    "sale_amount",
                    "commission_percent",
                    "commission_amount",
                )
            },
        ),
        (
            "Payment status",
            {
                "fields": (
                    "status",
                    "sale_date",
                    "paid_on",
                    "transaction_id",
                    "notes",
                )
            },
        ),
        (
            "System",
            {
                "classes": ("collapse",),
                "fields": ("created_at", "updated_at"),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "partner",
            "partner__user",
            "lead",
            "lead__sale_claim",
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._sync_sale_claim_from_commission(obj)

    def _sync_sale_claim_from_commission(self, commission):
        claim = getattr(commission.lead, "sale_claim", None)
        if claim is None:
            return
        claim.selling_price = commission.sale_amount
        claim.commission_percent = commission.commission_percent
        if commission.status == PartnerCommission.Status.PAID:
            claim.status = PartnerSaleClaim.Status.PAID
            claim.paid_at = timezone.make_aware(
                datetime.combine(commission.paid_on, time(12, 0))
            )
            claim.save(
                update_fields=[
                    "selling_price",
                    "commission_percent",
                    "status",
                    "paid_at",
                ]
            )
        elif commission.status == PartnerCommission.Status.CANCELLED:
            claim.status = PartnerSaleClaim.Status.REJECTED
            if not claim.admin_note:
                claim.admin_note = "Commission payment cancelled by admin."
            claim.save(
                update_fields=[
                    "selling_price",
                    "commission_percent",
                    "status",
                    "admin_note",
                ]
            )
        else:
            claim.status = PartnerSaleClaim.Status.APPROVED
            claim.approved_at = claim.approved_at or timezone.now()
            claim.save(
                update_fields=[
                    "selling_price",
                    "commission_percent",
                    "status",
                    "approved_at",
                ]
            )

    @admin.action(description="Mark selected commissions as paid")
    def mark_selected_as_paid(self, request, queryset):
        updated = 0
        today = timezone.localdate()
        for commission in queryset.exclude(status=PartnerCommission.Status.CANCELLED):
            commission.status = PartnerCommission.Status.PAID
            commission.paid_on = commission.paid_on or today
            commission.save(update_fields=["status", "paid_on", "updated_at"])
            self._sync_sale_claim_from_commission(commission)
            updated += 1
        self.message_user(request, f"{updated} commission(s) marked as paid.")


@admin.register(PartnerCallHistory)
class PartnerCallHistoryAdmin(admin.ModelAdmin):
    list_display = (
        "partner",
        "lead",
        "call_time",
        "result",
        "notes",
    )
    list_filter = ("result", "partner", "lead__city", "call_time")
    search_fields = (
        "partner__full_name",
        "partner__mobile",
        "partner__user__username",
        "lead__school_name",
        "lead__mobile",
        "lead__city",
        "notes",
    )
    autocomplete_fields = ("partner", "lead")
    date_hierarchy = "call_time"
    ordering = ("-call_time", "-created_at")
    readonly_fields = ("created_at",)
    fieldsets = (
        (
            "Call",
            {
                "fields": (
                    "partner",
                    "lead",
                    "call_time",
                    "result",
                    "notes",
                )
            },
        ),
        (
            "System",
            {
                "classes": ("collapse",),
                "fields": ("created_at",),
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "partner",
            "partner__user",
            "lead",
        )


@admin.register(PartnerSaleClaim)
class PartnerSaleClaimAdmin(admin.ModelAdmin):
    list_display = (
        "partner",
        "lead",
        "selling_price",
        "commission_percent",
        "commission_amount",
        "status",
        "commission_payment_status",
        "submitted_at",
        "approved_at",
        "paid_at",
    )
    list_filter = ("status", "partner", "submitted_at", "approved_at", "paid_at")
    search_fields = (
        "partner__full_name",
        "partner__mobile",
        "partner__user__username",
        "lead__school_name",
        "lead__mobile",
        "lead__city",
    )
    autocomplete_fields = ("partner", "lead")
    date_hierarchy = "submitted_at"
    ordering = ("-submitted_at",)
    readonly_fields = (
        "commission_amount",
        "submitted_at",
        "approved_at",
        "paid_at",
        "payment_screenshot_preview",
        "payment_screenshot_download",
        "manage_commission_payment",
        "commission_record_summary",
    )
    actions = (
        "approve_selected_claims",
        "mark_selected_claims_as_paid",
        "reject_selected_claims",
    )
    fieldsets = (
        (
            "Sale claim",
            {
                "fields": (
                    "partner",
                    "lead",
                    "selling_price",
                    "commission_percent",
                    "commission_amount",
                    "status",
                )
            },
        ),
        (
            "Payment proof",
            {
                "fields": (
                    "payment_screenshot",
                    "payment_screenshot_preview",
                    "payment_screenshot_download",
                    "payment_note",
                )
            },
        ),
        (
            "Admin review",
            {
                "fields": (
                    "admin_note",
                    "manage_commission_payment",
                    "commission_record_summary",
                    "submitted_at",
                    "approved_at",
                    "paid_at",
                )
            },
        ),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            "partner",
            "partner__user",
            "lead",
            "lead__commission",
        )

    @admin.display(description="Payment screenshot preview")
    def payment_screenshot_preview(self, obj):
        if not obj.payment_screenshot:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            '<img src="{}" style="max-height:160px;max-width:260px;border-radius:8px;" />'
            "</a>",
            obj.payment_screenshot.url,
            obj.payment_screenshot.url,
        )

    @admin.display(description="Download payment screenshot")
    def payment_screenshot_download(self, obj):
        if not obj.payment_screenshot:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener" download>Download screenshot</a>',
            obj.payment_screenshot.url,
        )

    @admin.display(description="Commission payment")
    def commission_payment_status(self, obj):
        commission = self._commission_for_claim(obj)
        if commission is None:
            return "Not created"
        return commission.get_status_display()

    @admin.display(description="Partner commission record")
    def commission_record_summary(self, obj):
        commission = self._commission_for_claim(obj)
        if commission is None:
            return "Commission record will be created automatically when this sale claim is saved."
        paid_on = commission.paid_on.isoformat() if commission.paid_on else "Not paid"
        return format_html(
            "Amount: <strong>{}</strong><br>Status: <strong>{}</strong><br>Paid on: {}",
            commission.commission_amount,
            commission.get_status_display(),
            paid_on,
        )

    @admin.display(description="Payment details")
    def manage_commission_payment(self, obj):
        if not obj or not obj.pk:
            return "Save this sale claim first, then add payment details."

        commission = self._commission_for_claim(obj)
        if commission is not None:
            url = reverse(
                "admin:UCMPartner_partnercommission_change",
                args=[commission.pk],
            )
        else:
            query = urlencode(
                {
                    "partner": obj.partner_id,
                    "lead": obj.lead_id,
                    "sale_amount": obj.selling_price,
                    "commission_percent": obj.commission_percent,
                    "status": PartnerCommission.Status.PENDING,
                    "sale_date": timezone.localdate().isoformat(),
                    "notes": f"Managed from sale claim #{obj.pk}. {obj.payment_note}".strip(),
                }
            )
            url = f"{reverse('admin:UCMPartner_partnercommission_add')}?{query}"

        return format_html(
            '<a class="button" href="{}">{}</a>',
            url,
            "Add / update payment details",
        )

    def _commission_for_claim(self, obj):
        if not obj or not obj.lead_id:
            return None
        return PartnerCommission.objects.filter(lead_id=obj.lead_id).first()

    @admin.action(description="Approve selected sale claims")
    def approve_selected_claims(self, request, queryset):
        updated = 0
        now = timezone.now()
        for claim in queryset.filter(status=PartnerSaleClaim.Status.PENDING_REVIEW):
            claim.status = PartnerSaleClaim.Status.APPROVED
            claim.approved_at = claim.approved_at or now
            claim.save(update_fields=["status", "approved_at"])
            updated += 1
        self.message_user(request, f"{updated} sale claim(s) approved.")

    @admin.action(description="Mark selected sale claims as paid")
    def mark_selected_claims_as_paid(self, request, queryset):
        updated = 0
        now = timezone.now()
        for claim in queryset.exclude(status=PartnerSaleClaim.Status.REJECTED):
            claim.status = PartnerSaleClaim.Status.PAID
            claim.approved_at = claim.approved_at or now
            claim.paid_at = claim.paid_at or now
            claim.save(update_fields=["status", "approved_at", "paid_at"])
            updated += 1
        self.message_user(request, f"{updated} sale claim(s) marked as paid.")

    @admin.action(description="Reject selected sale claims with admin note")
    def reject_selected_claims(self, request, queryset):
        updated = 0
        for claim in queryset.exclude(status=PartnerSaleClaim.Status.PAID):
            claim.status = PartnerSaleClaim.Status.REJECTED
            if not claim.admin_note:
                claim.admin_note = "Rejected by admin. Please contact Ultoxy support for details."
            claim.save(update_fields=["status", "admin_note"])
            updated += 1
        self.message_user(request, f"{updated} sale claim(s) rejected.")
