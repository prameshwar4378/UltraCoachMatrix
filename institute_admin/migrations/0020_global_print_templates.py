from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import institute_admin.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("institute_admin", "0019_instituteprinttemplate"),
    ]

    operations = [
        migrations.CreateModel(
            name="InstituteGlobalPrintTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "document_type",
                    models.CharField(
                        choices=[
                            ("ADMISSION_FORM", "Admission Form"),
                            ("TRANSFER_CERTIFICATE", "TC"),
                            ("BONAFIDE_CERTIFICATE", "Bonafide"),
                        ],
                        max_length=40,
                    ),
                ),
                ("title", models.CharField(max_length=160)),
                ("description", models.CharField(blank=True, max_length=255)),
                (
                    "html_file",
                    models.FileField(upload_to=institute_admin.models.global_print_template_upload_path),
                ),
                (
                    "preview_image",
                    models.ImageField(
                        blank=True,
                        upload_to=institute_admin.models.global_print_template_preview_upload_path,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_global_print_templates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["document_type", "title"],
            },
        ),
        migrations.AlterField(
            model_name="instituteprinttemplate",
            name="document_type",
            field=models.CharField(
                choices=[
                    ("ADMISSION_FORM", "Admission Form"),
                    ("TRANSFER_CERTIFICATE", "TC"),
                    ("BONAFIDE_CERTIFICATE", "Bonafide"),
                ],
                max_length=40,
            ),
        ),
        migrations.AlterField(
            model_name="instituteprinttemplate",
            name="html_file",
            field=models.FileField(blank=True, upload_to=institute_admin.models.institute_print_template_upload_path),
        ),
        migrations.AddField(
            model_name="instituteprinttemplate",
            name="library_template",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="institute_assignments",
                to="institute_admin.instituteglobalprinttemplate",
            ),
        ),
        migrations.AddIndex(
            model_name="instituteglobalprinttemplate",
            index=models.Index(fields=["document_type", "is_active"], name="igpt_type_active_idx"),
        ),
    ]
