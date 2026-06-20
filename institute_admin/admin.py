from django.contrib import admin
from django.utils.html import format_html

from .models import InstituteGlobalPrintTemplate


@admin.register(InstituteGlobalPrintTemplate)
class InstituteGlobalPrintTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "document_type", "is_active", "preview_thumb", "updated_at")
    list_filter = ("document_type", "is_active", "updated_at")
    search_fields = ("title", "description")
    readonly_fields = ("preview_thumb", "created_at", "updated_at")
    fields = (
        "document_type",
        "title",
        "description",
        "html_file",
        "preview_image",
        "preview_thumb",
        "is_active",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Preview")
    def preview_thumb(self, obj):
        if not obj or not obj.preview_image:
            return "-"
        return format_html(
            '<img src="{}" style="width:120px;height:80px;object-fit:cover;border:1px solid #d1d5db;border-radius:8px;" />',
            obj.preview_image.url,
        )

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
