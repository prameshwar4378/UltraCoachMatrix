from django.db import transaction

from teacher.models import Attendance

from .dashboard_cache import invalidate_dashboard_summary
from UltraCoachMatrix.email_notifications import on_commit_email, send_attendance_alerts


def bulk_save_attendance(
    *,
    student_sessions,
    posted_student_ids,
    form_data,
    batch,
    attendance_date,
    marked_by,
):
    student_ids = {
        int(student_id)
        for student_id in posted_student_ids
        if str(student_id).isdigit()
    }
    if not student_ids:
        return 0

    sessions = {
        session.student_id: session
        for session in student_sessions.filter(student_id__in=student_ids).only(
            "pk",
            "student_id",
            "institute_id",
            "academic_year_id",
        )
    }
    if not sessions:
        return 0

    existing_records = {
        record.academic_session_id: record
        for record in Attendance.objects.filter(
            academic_session_id__in=[session.pk for session in sessions.values()],
            batch=batch,
            date=attendance_date,
        )
    }
    to_create = []
    to_update = []
    alert_records = []

    for student_id, session in sessions.items():
        status = form_data.get(f"status_{student_id}", Attendance.Status.PRESENT)
        if status not in Attendance.Status.values:
            status = Attendance.Status.PRESENT
        note = form_data.get(f"note_{student_id}", "").strip()
        record = existing_records.get(session.pk)
        if record:
            previous_status = record.status
            record.student_id = student_id
            record.status = status
            record.note = note
            record.marked_by = marked_by
            to_update.append(record)
            if status in {Attendance.Status.ABSENT, Attendance.Status.LATE} and status != previous_status:
                alert_records.append(record)
        else:
            record = Attendance(
                student_id=student_id,
                academic_session_id=session.pk,
                batch=batch,
                date=attendance_date,
                status=status,
                note=note,
                marked_by=marked_by,
            )
            to_create.append(record)
            if status in {Attendance.Status.ABSENT, Attendance.Status.LATE}:
                alert_records.append(record)

    with transaction.atomic():
        if to_create:
            Attendance.objects.bulk_create(to_create, batch_size=500)
        if to_update:
            Attendance.objects.bulk_update(
                to_update,
                ["student", "status", "note", "marked_by"],
                batch_size=500,
            )
        alert_ids = [record.pk for record in alert_records if record.pk]
        if alert_ids:
            on_commit_email(send_attendance_alerts, alert_ids)

    sample_session = next(iter(sessions.values()))
    invalidate_dashboard_summary(
        sample_session.institute_id,
        sample_session.academic_year_id,
    )
    return len(to_create) + len(to_update)
