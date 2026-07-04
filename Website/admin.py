from django.contrib import admin

from .models import ContactEnquiry, WebsiteFeedback


@admin.register(ContactEnquiry)
class ContactEnquiryAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "phone", "email", "enquiry_type", "status", "created_at")
    list_filter = ("enquiry_type", "institution_size", "status", "created_at")
    search_fields = ("name", "school", "phone", "email", "message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(WebsiteFeedback)
class WebsiteFeedbackAdmin(admin.ModelAdmin):
    list_display = ("name", "institute", "rating", "is_visible", "created_at")
    list_filter = ("rating", "is_visible", "created_at")
    search_fields = ("name", "institute", "feedback")
    readonly_fields = ("created_at",)
