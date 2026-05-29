from django.db import migrations


def backfill_session_links(apps, schema_editor):
    StudentAcademicSession = apps.get_model("student_parent", "StudentAcademicSession")
    StudentEnrollment = apps.get_model("student_parent", "StudentEnrollment")
    FeeInvoice = apps.get_model("accountant", "FeeInvoice")
    Attendance = apps.get_model("teacher", "Attendance")

    session_by_student_year = {
        (session.student_id, session.academic_year_id): session.pk
        for session in StudentAcademicSession.objects.all().only("id", "student_id", "academic_year_id")
    }
    first_session_by_student = {}
    for session in StudentAcademicSession.objects.all().order_by("academic_year__start_date", "pk"):
        first_session_by_student.setdefault(session.student_id, session.pk)

    def resolve_session_id(student):
        if not student:
            return None
        session_id = None
        if getattr(student, "academic_year_id", None):
            session_id = session_by_student_year.get((student.pk, student.academic_year_id))
        return session_id or first_session_by_student.get(student.pk)

    for enrollment in StudentEnrollment.objects.select_related("student").filter(academic_session__isnull=True):
        session_id = resolve_session_id(enrollment.student)
        if session_id:
            enrollment.academic_session_id = session_id
            enrollment.save(update_fields=["academic_session"])

    for invoice in FeeInvoice.objects.select_related("student", "enrollment").filter(academic_session__isnull=True):
        session_id = invoice.enrollment.academic_session_id if invoice.enrollment_id else resolve_session_id(invoice.student)
        if session_id:
            invoice.academic_session_id = session_id
            invoice.save(update_fields=["academic_session"])

    for attendance in Attendance.objects.select_related("student").filter(academic_session__isnull=True):
        session_id = resolve_session_id(attendance.student)
        if session_id:
            attendance.academic_session_id = session_id
            attendance.save(update_fields=["academic_session"])


class Migration(migrations.Migration):

    dependencies = [
        ("institute_admin", "0004_academicyear"),
        ("student_parent", "0008_alter_studentenrollment_options_and_more"),
        ("accountant", "0004_feeinvoice_academic_session"),
        ("teacher", "0006_alter_attendance_unique_together_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_session_links, migrations.RunPython.noop),
    ]
