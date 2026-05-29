from datetime import date

from django.db import migrations


def current_academic_year_name():
    today = date.today()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def assign_existing_students(apps, schema_editor):
    AcademicYear = apps.get_model("institute_admin", "AcademicYear")
    StudentProfile = apps.get_model("student_parent", "StudentProfile")
    name = current_academic_year_name()
    start_year = int(name.split("-", 1)[0])
    start_date = date(start_year, 4, 1)
    end_date = date(start_year + 1, 3, 31)

    institute_ids = StudentProfile.objects.filter(academic_year__isnull=True).values_list("institute_id", flat=True).distinct()
    for institute_id in institute_ids:
        academic_year, _created = AcademicYear.objects.get_or_create(
            institute_id=institute_id,
            name=name,
            defaults={
                "start_date": start_date,
                "end_date": end_date,
                "is_active": True,
            },
        )
        StudentProfile.objects.filter(institute_id=institute_id, academic_year__isnull=True).update(academic_year=academic_year)


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0004_academicyear"),
        ("student_parent", "0004_alter_studentprofile_unique_together_and_more"),
    ]

    operations = [
        migrations.RunPython(assign_existing_students, migrations.RunPython.noop),
    ]
