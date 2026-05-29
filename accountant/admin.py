from django.contrib import admin

from .models import Expense, FeeCategory, FeeInvoice, Payment, PaymentActivity


@admin.register(FeeCategory)
class FeeCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "default_amount", "is_active")
    list_filter = ("institute", "is_active")
    search_fields = ("name",)


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(FeeInvoice)
class FeeInvoiceAdmin(admin.ModelAdmin):
    list_display = ("academic_session", "student", "title", "course", "batch", "amount", "due_date", "status", "institute")
    list_filter = ("institute", "academic_session__academic_year", "course", "batch", "status", "due_date")
    search_fields = ("academic_session__admission_number", "student__user__username", "title")
    inlines = [PaymentInline]


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("invoice", "amount", "paid_on", "method", "status", "received_by", "receipt_number")
    list_filter = ("method", "status", "paid_on")
    search_fields = ("invoice__academic_session__admission_number", "invoice__title", "receipt_number")


@admin.register(PaymentActivity)
class PaymentActivityAdmin(admin.ModelAdmin):
    list_display = ("payment", "action", "performed_by", "performed_at", "old_amount", "new_amount")
    list_filter = ("action", "performed_at")
    search_fields = ("payment__invoice__academic_session__admission_number", "payment__invoice__title", "note")


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("title", "institute", "amount", "spent_on", "recorded_by")
    list_filter = ("institute", "spent_on")
    search_fields = ("title", "note")
