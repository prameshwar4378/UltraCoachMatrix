from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0017_student_bonafide_certificate"),
    ]

    operations = [
        migrations.AddField(
            model_name="studentprofile",
            name="pen_no",
            field=models.CharField(blank=True, max_length=80, verbose_name="PEN No"),
        ),
        migrations.AddField(
            model_name="studentprofile",
            name="appar_id",
            field=models.CharField(blank=True, max_length=80, verbose_name="Appar ID"),
        ),
        migrations.AddField(
            model_name="studentprofile",
            name="cast",
            field=models.CharField(blank=True, max_length=80, verbose_name="Cast"),
        ),
    ]
