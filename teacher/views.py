from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.dateparse import parse_date

from institute_admin.models import Batch
from student_parent.models import StudentAcademicSession, StudentEnrollment
from student_parent.notifications import notify_result_declared
from super_admin.decorators import teacher_required
from .forms import TeacherExamForm, TeacherExamResultForm, TeacherHomeworkForm
from .models import Attendance, Exam, ExamResult, Homework


def teacher_batches(request):
    profile = getattr(request.user, "profile", None)
    if not profile or not profile.institute_id:
        return Batch.objects.none()
    return Batch.objects.filter(
        institute=profile.institute,
        teachers=request.user,
        is_active=True,
    ).prefetch_related("courses")


def teacher_students_for_batches(batches):
    return (
        StudentAcademicSession.objects.filter(
            enrollments__batch__in=batches,
            enrollments__status=StudentEnrollment.Status.ACTIVE,
            status=StudentAcademicSession.Status.ACTIVE,
            student__is_active=True,
        )
        .select_related("student", "student__user")
        .distinct()
        .order_by("admission_number", "student__user__first_name", "student__user__username")
    )


@teacher_required
def dashboard(request):
    batches = teacher_batches(request)
    today = date.today()
    context = {
        "batch_count": batches.count(),
        "student_count": teacher_students_for_batches(batches).count(),
        "homework_count": Homework.objects.filter(batch__in=batches).count(),
        "exam_count": Exam.objects.filter(batch__in=batches).count(),
        "today_attendance_count": Attendance.objects.filter(batch__in=batches, date=today).count(),
        "recent_homework": Homework.objects.filter(batch__in=batches).select_related("batch", "course")[:6],
        "recent_exams": Exam.objects.filter(batch__in=batches).select_related("batch")[:6],
    }
    return render(request, "teacher/dashboard.html", context)


@teacher_required
def attendance(request):
    batches = teacher_batches(request)
    selected_date = parse_date(request.GET.get("date", "")) or date.today()
    selected_batch = batches.filter(pk=request.GET.get("batch")).first() or batches.first()
    students = StudentAcademicSession.objects.none()
    attendance_map = {}

    if selected_batch:
        students = teacher_students_for_batches(batches.filter(pk=selected_batch.pk))
        attendance_map = {
            record.academic_session_id: record
            for record in Attendance.objects.filter(
                batch=selected_batch,
                date=selected_date,
                academic_session__in=students,
            )
        }

    if request.method == "POST" and selected_batch:
        saved_count = 0
        for session in students:
            status = request.POST.get(f"status_{session.pk}", Attendance.Status.PRESENT)
            note = request.POST.get(f"note_{session.pk}", "").strip()
            if status not in Attendance.Status.values:
                status = Attendance.Status.PRESENT
            Attendance.objects.update_or_create(
                academic_session=session,
                batch=selected_batch,
                date=selected_date,
                defaults={
                    "student": session.student,
                    "status": status,
                    "note": note,
                    "marked_by": request.user,
                },
            )
            saved_count += 1
        messages.success(request, f"Attendance saved for {saved_count} student(s).")
        return redirect(f"{reverse('teacher:attendance')}?batch={selected_batch.pk}&date={selected_date.isoformat()}")

    rows = [
        {
            "session": session,
            "record": attendance_map.get(session.pk),
            "status": attendance_map.get(session.pk).status if attendance_map.get(session.pk) else Attendance.Status.PRESENT,
            "note": attendance_map.get(session.pk).note if attendance_map.get(session.pk) else "",
        }
        for session in students
    ]
    return render(
        request,
        "teacher/attendance.html",
        {
            "batches": batches,
            "selected_batch": selected_batch,
            "selected_date": selected_date,
            "rows": rows,
            "status_choices": Attendance.Status.choices,
            "present_value": Attendance.Status.PRESENT,
            "absent_value": Attendance.Status.ABSENT,
            "late_value": Attendance.Status.LATE,
        },
    )


@teacher_required
def homework(request):
    batches = teacher_batches(request)
    items = Homework.objects.filter(batch__in=batches).select_related("batch", "course", "created_by")
    search = request.GET.get("search", "").strip()
    if search:
        items = items.filter(Q(title__icontains=search) | Q(instructions__icontains=search) | Q(batch__name__icontains=search))
    return render(request, "teacher/homework.html", {"homework_list": items, "search": search})


@teacher_required
def homework_create(request):
    batches = teacher_batches(request)
    form = TeacherHomeworkForm(request.POST or None, request.FILES or None, batches=batches)
    if request.method == "POST" and form.is_valid():
        homework = form.save(commit=False)
        homework.created_by = request.user
        homework.save()
        form.save_attachments(homework)
        messages.success(request, "Homework created successfully.")
        return redirect("teacher:homework")
    return render(request, "teacher/homework_form.html", {"form": form, "title": "Create Homework"})


@teacher_required
def exams(request):
    batches = teacher_batches(request)
    return render(
        request,
        "teacher/exams.html",
        {"exams": Exam.objects.filter(batch__in=batches).select_related("batch")},
    )


@teacher_required
def exam_create(request):
    batches = teacher_batches(request)
    form = TeacherExamForm(request.POST or None, batches=batches)
    if request.method == "POST" and form.is_valid():
        exam = form.save(commit=False)
        exam.created_by = request.user
        exam.save()
        messages.success(request, "Exam created successfully.")
        return redirect("teacher:exams")
    return render(request, "teacher/exam_form.html", {"form": form, "title": "Create Exam"})


@teacher_required
def results(request):
    batches = teacher_batches(request)
    exams_qs = Exam.objects.filter(batch__in=batches)
    result_qs = ExamResult.objects.filter(exam__in=exams_qs).select_related("exam", "student", "student__user")
    return render(request, "teacher/results.html", {"results": result_qs})


@teacher_required
def result_create(request):
    batches = teacher_batches(request)
    exams_qs = Exam.objects.filter(batch__in=batches)
    students_qs = teacher_students_for_batches(batches).values_list("student_id", flat=True)
    from student_parent.models import StudentProfile

    form = TeacherExamResultForm(
        request.POST or None,
        exams=exams_qs,
        students=StudentProfile.objects.filter(pk__in=students_qs).select_related("user"),
    )
    if request.method == "POST" and form.is_valid():
        result = form.save()
        notify_result_declared(result)
        messages.success(request, "Result saved successfully.")
        return redirect("teacher:results")
    return render(request, "teacher/result_form.html", {"form": form, "title": "Add Result"})
