import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def split_existing_names(apps, schema_editor):
    Lead = apps.get_model("institute_admin", "Lead")
    for lead in Lead.objects.all().iterator():
        parts = (lead.first_name or "").strip().split(maxsplit=1)
        lead.first_name = parts[0] if parts else "Unknown"
        lead.last_name = parts[1] if len(parts) > 1 else ""
        lead.save(update_fields=["first_name", "last_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0010_enquiry"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameModel(old_name="Enquiry", new_name="Lead"),
        migrations.RenameField(model_name="lead", old_name="name", new_name="first_name"),
        migrations.RenameField(model_name="lead", old_name="phone", new_name="mobile_number"),
        migrations.RenameField(model_name="lead", old_name="interested_course", new_name="interested_class"),
        migrations.RenameField(model_name="lead", old_name="notes", new_name="message"),
        migrations.AlterField(
            model_name="lead",
            name="first_name",
            field=models.CharField(max_length=150),
        ),
        migrations.AddField(
            model_name="lead",
            name="last_name",
            field=models.CharField(blank=True, default="", max_length=150),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="lead",
            name="interested_batch",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leads", to="institute_admin.batch"),
        ),
        migrations.AlterField(
            model_name="lead",
            name="created_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_leads", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="lead",
            name="institute",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="leads", to="super_admin.institute"),
        ),
        migrations.AlterField(
            model_name="lead",
            name="interested_class",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="leads", to="institute_admin.course"),
        ),
        migrations.RunPython(split_existing_names, migrations.RunPython.noop),
        migrations.RemoveIndex(model_name="lead", name="enquiry_inst_status_idx"),
        migrations.AddIndex(
            model_name="lead",
            index=models.Index(fields=["institute", "status", "-created_at"], name="lead_inst_status_idx"),
        ),
    ]
