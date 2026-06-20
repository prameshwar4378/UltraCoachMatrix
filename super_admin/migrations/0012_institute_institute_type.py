from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("super_admin", "0011_institute_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="institute",
            name="institute_type",
            field=models.CharField(
                choices=[
                    ("COACHING_CLASSES", "Coaching Classes"),
                    ("SCHOOL", "School"),
                ],
                default="COACHING_CLASSES",
                max_length=20,
            ),
        ),
    ]
