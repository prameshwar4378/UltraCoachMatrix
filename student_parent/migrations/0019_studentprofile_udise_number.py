from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0018_studentprofile_appar_id_pen_no_cast"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studentprofile",
            name="gr_number_udise",
            field=models.CharField(blank=True, max_length=80, verbose_name="GR Number"),
        ),
        migrations.AddField(
            model_name="studentprofile",
            name="udise_number",
            field=models.CharField(blank=True, max_length=80, verbose_name="UDISE Number"),
        ),
    ]
