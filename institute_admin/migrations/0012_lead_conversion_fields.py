import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0011_rename_enquiry_lead_and_expand_fields"),
        ("student_parent", "0012_guardianprofile_guardian_primary_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="lead",
            name="converted_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="lead",
            name="converted_student",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="converted_from_lead",
                to="student_parent.studentprofile",
            ),
        ),
    ]
