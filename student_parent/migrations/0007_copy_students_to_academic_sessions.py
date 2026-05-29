from django.db import migrations


def copy_students_to_academic_sessions(apps, schema_editor):
    StudentProfile = apps.get_model("student_parent", "StudentProfile")
    StudentAcademicSession = apps.get_model("student_parent", "StudentAcademicSession")
    AcademicYear = apps.get_model("institute_admin", "AcademicYear")

    for student in StudentProfile.objects.select_related("institute", "academic_year").all():
        academic_year = student.academic_year
        if academic_year is None:
            academic_year = AcademicYear.objects.filter(institute_id=student.institute_id).order_by("-start_date").first()
        if academic_year is None:
            continue

        StudentAcademicSession.objects.update_or_create(
            student_id=student.id,
            academic_year_id=academic_year.id,
            defaults={
                "institute_id": student.institute_id,
                "admission_number": student.admission_number,
                "joined_on": student.joined_on,
                "status": "ACTIVE" if student.is_active else "LEFT",
                "current_school_name": student.current_school_name,
                "current_school_address": student.current_school_address,
                "previous_school_name": student.previous_school_name,
                "previous_class": student.previous_class,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ("student_parent", "0006_studentacademicsession"),
    ]

    operations = [
        migrations.RunPython(copy_students_to_academic_sessions, migrations.RunPython.noop),
    ]
