from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0022_simplify_student_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="studenttransfercertificate",
            name="tc_type",
            field=models.CharField(
                choices=[("ORIGINAL", "Original"), ("DUPLICATE", "Duplicate")],
                default="ORIGINAL",
                max_length=20,
            ),
        ),
    ]
