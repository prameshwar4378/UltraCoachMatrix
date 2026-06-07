import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.utils import timezone

import institute_admin.models


def copy_visitor_data(apps, schema_editor):
    Visitor = apps.get_model("institute_admin", "Visitor")
    for visitor in Visitor.objects.all().iterator():
        visitor.visitor_name = " ".join(
            part for part in (visitor.visitor_name, visitor.last_name) if part
        )
        if visitor.visit_on:
            local_visit = timezone.localtime(visitor.visit_on)
            visitor.visit_date = local_visit.date()
            visitor.entry_time = local_visit.time().replace(second=0, microsecond=0)
        visitor.save(
            update_fields=("visitor_name", "visit_date", "entry_time")
        )


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0013_visitor"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(
            model_name="visitor",
            old_name="first_name",
            new_name="visitor_name",
        ),
        migrations.RenameField(
            model_name="visitor",
            old_name="mobile_number",
            new_name="phone_number",
        ),
        migrations.RemoveIndex(
            model_name="visitor",
            name="visitor_inst_status_idx",
        ),
        migrations.AddField(
            model_name="visitor",
            name="attachment",
            field=models.FileField(
                blank=True,
                upload_to="visitors/id_scans/",
                verbose_name="Attachment / ID Scan",
            ),
        ),
        migrations.AddField(
            model_name="visitor",
            name="entry_time",
            field=models.TimeField(
                default=institute_admin.models.default_visitor_entry_time
            ),
        ),
        migrations.AddField(
            model_name="visitor",
            name="exit_time",
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="visitor",
            name="id_card_number",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="ID Card / Pass No",
            ),
        ),
        migrations.AddField(
            model_name="visitor",
            name="meeting_with",
            field=models.CharField(default="", max_length=200),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="visitor",
            name="total_person",
            field=models.PositiveIntegerField(
                default=1,
                validators=[django.core.validators.MinValueValidator(1)],
            ),
        ),
        migrations.AddField(
            model_name="visitor",
            name="visit_date",
            field=models.DateField(default=timezone.localdate),
        ),
        migrations.RunPython(copy_visitor_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name="visitor", name="email"),
        migrations.RemoveField(model_name="visitor", name="interested_batch"),
        migrations.RemoveField(model_name="visitor", name="interested_class"),
        migrations.RemoveField(model_name="visitor", name="last_name"),
        migrations.RemoveField(model_name="visitor", name="message"),
        migrations.RemoveField(model_name="visitor", name="status"),
        migrations.RemoveField(model_name="visitor", name="visit_on"),
        migrations.AlterField(
            model_name="visitor",
            name="purpose",
            field=models.TextField(blank=True, verbose_name="Purpose of Visit"),
        ),
        migrations.AlterField(
            model_name="visitor",
            name="visitor_name",
            field=models.CharField(max_length=200),
        ),
        migrations.AlterModelOptions(
            name="visitor",
            options={
                "ordering": ["-visit_date", "-entry_time", "-created_at"]
            },
        ),
        migrations.AddIndex(
            model_name="visitor",
            index=models.Index(
                fields=["institute", "-visit_date", "-entry_time"],
                name="visitor_inst_visit_idx",
            ),
        ),
    ]
