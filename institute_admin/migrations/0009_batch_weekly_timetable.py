from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0008_subject"),
    ]

    operations = [
        migrations.AddField(
            model_name="batch",
            name="weekly_timetable",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
