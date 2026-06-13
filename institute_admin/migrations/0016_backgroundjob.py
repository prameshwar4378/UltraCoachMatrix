import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("institute_admin", "0015_supportticket"),
        ("super_admin", "0010_alter_institute_options_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="BackgroundJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_type", models.CharField(choices=[("STUDENT_IMPORT", "Student import"), ("FEE_NOTIFICATION", "Fee notification"), ("NOTICE_NOTIFICATION", "Notice notification")], max_length=40)),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("RUNNING", "Running"), ("COMPLETED", "Completed"), ("FAILED", "Failed")], default="PENDING", max_length=20)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("input_file", models.FileField(blank=True, upload_to="background_jobs/input/")),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("academic_year", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="background_jobs", to="institute_admin.academicyear")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="background_jobs", to=settings.AUTH_USER_MODEL)),
                ("institute", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="background_jobs", to="super_admin.institute")),
            ],
            options={
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(fields=["status", "created_at"], name="bgjob_status_created_idx"),
                    models.Index(fields=["institute", "job_type", "status"], name="bgjob_inst_type_idx"),
                ],
            },
        ),
    ]
