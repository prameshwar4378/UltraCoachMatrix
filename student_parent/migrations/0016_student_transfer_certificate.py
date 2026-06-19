from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("student_parent", "0015_expand_student_admission_fields"),
        ("super_admin", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="StudentTransferCertificate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("tc_number", models.CharField(max_length=60)),
                ("issue_date", models.DateField()),
                ("leaving_date", models.DateField()),
                ("reason_for_leaving", models.CharField(max_length=255)),
                ("conduct", models.CharField(max_length=120)),
                ("result", models.CharField(blank=True, max_length=80)),
                ("last_class_attended", models.CharField(max_length=80)),
                ("qualified_for_promotion", models.BooleanField(default=False)),
                ("fees_cleared", models.BooleanField(default=False)),
                ("remarks", models.CharField(blank=True, max_length=255)),
                ("student_snapshot", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[("GENERATED", "Generated"), ("CANCELLED", "Cancelled")],
                        default="GENERATED",
                        max_length=20,
                    ),
                ),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_reason", models.CharField(blank=True, max_length=255)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "academic_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="transfer_certificates",
                        to="student_parent.studentacademicsession",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cancelled_transfer_certificates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "generated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="generated_transfer_certificates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "institute",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="student_transfer_certificates",
                        to="super_admin.institute",
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="transfer_certificates",
                        to="student_parent.studentprofile",
                    ),
                ),
            ],
            options={
                "ordering": ["-generated_at", "-pk"],
                "unique_together": {("institute", "tc_number")},
            },
        ),
        migrations.AddIndex(
            model_name="studenttransfercertificate",
            index=models.Index(fields=["student", "status", "-generated_at"], name="stc_student_status_idx"),
        ),
        migrations.AddIndex(
            model_name="studenttransfercertificate",
            index=models.Index(fields=["institute", "tc_number"], name="stc_inst_tc_idx"),
        ),
    ]
