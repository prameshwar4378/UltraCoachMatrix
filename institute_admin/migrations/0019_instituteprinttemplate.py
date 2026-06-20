from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import institute_admin.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("institute_admin", "0018_notice_push_notification_version"),
        ("super_admin", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="InstitutePrintTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("ADMISSION_FORM", "Admission Form"),
                            ("TRANSFER_CERTIFICATE", "Transfer Certificate"),
                            ("BONAFIDE_CERTIFICATE", "Bonafide Certificate"),
                        ],
                        max_length=40,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                (
                    "html_file",
                    models.FileField(upload_to=institute_admin.models.institute_print_template_upload_path),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "institute",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="print_templates",
                        to="super_admin.institute",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_print_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["document_type", "-updated_at"],
                "unique_together": {("institute", "document_type")},
            },
        ),
        migrations.AddIndex(
            model_name="instituteprinttemplate",
            index=models.Index(fields=["institute", "document_type", "is_active"], name="ipt_inst_type_active_idx"),
        ),
    ]
