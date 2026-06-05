from io import BytesIO

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook

from institute_admin.models import AcademicYear, Batch, Course, Subject
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.models import Institute, UserProfile
from teacher.forms import TeacherExamForm, TeacherHomeworkForm
from teacher.models import Attendance, Exam, ExamAttempt, ExamQuestion, ExamQuestionAttempt, ExamQuestionOption, ExamResult, Homework


class ExamYearScopeTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(name="Scope Institute", code="scope")
        self.year_a = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date="2026-04-01",
            end_date="2027-03-31",
        )
        self.year_b = AcademicYear.objects.create(
            institute=self.institute,
            name="2027-28",
            start_date="2027-04-01",
            end_date="2028-03-31",
        )
        self.teacher_user = User.objects.create_user(username="teacher", password="pass")
        UserProfile.objects.create(
            user=self.teacher_user,
            institute=self.institute,
            role=UserProfile.Role.TEACHER,
        )
        self.student_user = User.objects.create_user(username="student", password="pass")
        UserProfile.objects.create(
            user=self.student_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        self.student = StudentProfile.objects.create(
            institute=self.institute,
            academic_year=self.year_a,
            user=self.student_user,
            admission_number="A001",
        )
        self.course_a = Course.objects.create(institute=self.institute, academic_year=self.year_a, name="Physics")
        self.course_b = Course.objects.create(institute=self.institute, academic_year=self.year_b, name="Physics")
        self.subject_a = Subject.objects.create(institute=self.institute, academic_year=self.year_a, name="Physics")
        self.subject_b = Subject.objects.create(institute=self.institute, academic_year=self.year_b, name="Maths")
        self.batch_a = Batch.objects.create(institute=self.institute, academic_year=self.year_a, name="Batch A")
        self.batch_a.courses.add(self.course_a)
        self.batch_a.teachers.add(self.teacher_user)
        self.unassigned_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year_a,
            name="Unassigned Batch",
        )
        self.unassigned_batch.courses.add(self.course_a)
        self.batch_b = Batch.objects.create(institute=self.institute, academic_year=self.year_b, name="Batch B")
        self.batch_b.courses.add(self.course_b)
        self.batch_b.teachers.add(self.teacher_user)
        self.session_a = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.year_a,
            admission_number="A001",
        )
        self.session_b = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.student,
            academic_year=self.year_b,
            admission_number="B001",
        )
        StudentEnrollment.objects.create(student=self.student, academic_session=self.session_a, batch=self.batch_a)
        StudentEnrollment.objects.create(student=self.student, academic_session=self.session_b, batch=self.batch_b)
        self.second_student_user = User.objects.create_user(username="student-two", password="pass")
        UserProfile.objects.create(
            user=self.second_student_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        self.second_student = StudentProfile.objects.create(
            institute=self.institute,
            academic_year=self.year_a,
            user=self.second_student_user,
            admission_number="A002",
        )
        self.second_session_a = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.second_student,
            academic_year=self.year_a,
            admission_number="A002",
        )
        StudentEnrollment.objects.create(student=self.second_student, academic_session=self.second_session_a, batch=self.batch_a)
        self.unassigned_student_user = User.objects.create_user(username="unassigned-student", password="pass")
        UserProfile.objects.create(
            user=self.unassigned_student_user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        self.unassigned_student = StudentProfile.objects.create(
            institute=self.institute,
            academic_year=self.year_a,
            user=self.unassigned_student_user,
            admission_number="U001",
        )
        self.unassigned_session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=self.unassigned_student,
            academic_year=self.year_a,
            admission_number="U001",
        )
        StudentEnrollment.objects.create(
            student=self.unassigned_student,
            academic_session=self.unassigned_session,
            batch=self.unassigned_batch,
        )
        self.exam_a = Exam.objects.create(
            academic_year=self.year_a,
            batch=self.batch_a,
            course=self.course_a,
            title="Year A Exam",
            exam_date="2026-06-10",
            is_published=True,
        )
        self.exam_b = Exam.objects.create(
            academic_year=self.year_b,
            batch=self.batch_b,
            course=self.course_b,
            title="Year B Exam",
            exam_date="2027-06-10",
            is_published=True,
        )
        self.unassigned_exam = Exam.objects.create(
            academic_year=self.year_a,
            batch=self.unassigned_batch,
            course=self.course_a,
            title="Unassigned Exam",
            exam_date="2026-06-11",
            is_published=True,
        )

    def test_teacher_exams_use_selected_academic_year(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:exams"))

        self.assertContains(response, "Year A Exam")
        self.assertNotContains(response, "Year B Exam")
        self.assertNotContains(response, "Unassigned Exam")

    def test_teacher_dashboard_counts_only_assigned_batches(self):
        Homework.objects.create(
            batch=self.batch_a,
            course=self.course_a,
            title="Assigned Homework",
            due_date="2026-06-20",
            created_by=self.teacher_user,
        )
        Homework.objects.create(
            batch=self.unassigned_batch,
            course=self.course_a,
            title="Unassigned Homework",
            due_date="2026-06-20",
            created_by=self.teacher_user,
        )
        Attendance.objects.create(
            student=self.student,
            academic_session=self.session_a,
            batch=self.batch_a,
            date=timezone.localdate(),
            status=Attendance.Status.PRESENT,
            marked_by=self.teacher_user,
        )
        Attendance.objects.create(
            student=self.unassigned_student,
            academic_session=self.unassigned_session,
            batch=self.unassigned_batch,
            date=timezone.localdate(),
            status=Attendance.Status.PRESENT,
            marked_by=self.teacher_user,
        )
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:dashboard"))

        self.assertEqual(response.context["batch_count"], 1)
        self.assertEqual(response.context["student_count"], 2)
        self.assertEqual(response.context["homework_count"], 1)
        self.assertEqual(response.context["exam_count"], 1)
        self.assertEqual(response.context["today_attendance_count"], 1)

    def test_teacher_homework_is_limited_to_assigned_batches(self):
        assigned_homework = Homework.objects.create(
            batch=self.batch_a,
            course=self.course_a,
            title="Assigned Homework",
            due_date="2026-06-20",
            created_by=self.teacher_user,
        )
        unassigned_homework = Homework.objects.create(
            batch=self.unassigned_batch,
            course=self.course_a,
            title="Unassigned Homework",
            due_date="2026-06-20",
            created_by=self.teacher_user,
        )
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:homework"))

        self.assertContains(response, assigned_homework.title)
        self.assertNotContains(response, unassigned_homework.title)
        self.assertEqual(self.client.get(reverse("teacher:homework_update", args=[unassigned_homework.pk])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("teacher:homework_delete", args=[unassigned_homework.pk])).status_code,
            404,
        )

    def test_teacher_homework_form_rejects_unassigned_batch(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(
            reverse("teacher:homework_create"),
            {
                "batch": str(self.unassigned_batch.pk),
                "course": str(self.course_a.pk),
                "title": "Should Not Save",
                "instructions": "Private",
                "due_date": "2026-06-20",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Homework.objects.filter(title="Should Not Save").exists())

    def test_teacher_attendance_ignores_unassigned_batch_and_students(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:attendance"), {"batch": self.unassigned_batch.pk})

        self.assertContains(response, "Batch A")
        self.assertNotContains(response, "Unassigned Batch")
        self.assertNotContains(response, "unassigned-student")

        response = self.client.post(
            f"{reverse('teacher:attendance')}?batch={self.unassigned_batch.pk}&date=2026-06-15",
            {
                "student_ids": [str(self.unassigned_student.pk)],
                f"status_{self.unassigned_student.pk}": Attendance.Status.ABSENT,
                f"note_{self.unassigned_student.pk}": "Forged",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            Attendance.objects.filter(
                batch=self.unassigned_batch,
                academic_session=self.unassigned_session,
                date="2026-06-15",
            ).exists()
        )

    def test_teacher_attendance_export_excludes_unassigned_batch(self):
        Attendance.objects.create(
            student=self.student,
            academic_session=self.session_a,
            batch=self.batch_a,
            date="2026-06-15",
            status=Attendance.Status.PRESENT,
            marked_by=self.teacher_user,
        )
        Attendance.objects.create(
            student=self.unassigned_student,
            academic_session=self.unassigned_session,
            batch=self.unassigned_batch,
            date="2026-06-15",
            status=Attendance.Status.ABSENT,
            marked_by=self.teacher_user,
        )
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:attendance_export"), {"format": "excel"})

        workbook = load_workbook(BytesIO(response.content), data_only=True)
        worksheet = workbook.active
        values = "\n".join(str(cell.value or "") for row in worksheet.iter_rows() for cell in row)
        self.assertIn("A001", values)
        self.assertNotIn("U001", values)

    def test_teacher_exam_direct_urls_reject_unassigned_batch_exam(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        protected_urls = [
            reverse("teacher:exam_update", args=[self.unassigned_exam.pk]),
            reverse("teacher:exam_questions", args=[self.unassigned_exam.pk]),
            reverse("teacher:exam_question_create", args=[self.unassigned_exam.pk]),
            reverse("teacher:exam_question_import_template", args=[self.unassigned_exam.pk]),
            reverse("teacher:exam_submissions", args=[self.unassigned_exam.pk]),
        ]

        for url in protected_urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

        self.assertEqual(
            self.client.post(reverse("teacher:exam_toggle_result_publish", args=[self.unassigned_exam.pk]), {"action": "publish"}).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(reverse("teacher:exam_publish", args=[self.unassigned_exam.pk])).status_code,
            404,
        )

    def test_teacher_exam_form_rejects_unassigned_batch(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(
            reverse("teacher:exam_create"),
            {
                "batch": str(self.unassigned_batch.pk),
                "subject": str(self.subject_a.pk),
                "title": "Forbidden Exam",
                "exam_date": "2026-07-01",
                "duration_minutes": "60",
                "instructions": "Nope",
                "allow_rough_work_uploads": "on",
                "is_published": "on",
                "show_result_after_submit": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Exam.objects.filter(title="Forbidden Exam").exists())

    def test_teacher_results_are_limited_to_assigned_batch_exams(self):
        ExamResult.objects.create(exam=self.exam_a, student=self.student, marks_obtained=8)
        ExamResult.objects.create(exam=self.unassigned_exam, student=self.unassigned_student, marks_obtained=9)
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:results"))

        self.assertContains(response, "Year A Exam")
        self.assertNotContains(response, "Unassigned Exam")

    def test_teacher_result_form_rejects_unassigned_exam(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(
            reverse("teacher:result_create"),
            {
                "exam": str(self.unassigned_exam.pk),
                "student": str(self.unassigned_student.pk),
                "marks_obtained": "5",
                "remark": "Forbidden",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExamResult.objects.filter(exam=self.unassigned_exam, remark="Forbidden").exists())

    def test_student_exams_use_selected_academic_session_year(self):
        self.client.login(username="student", password="pass")

        response = self.client.get(
            reverse("student_parent:exams"),
            {"academic_session_id": self.session_b.pk},
        )

        self.assertContains(response, "Year B Exam")
        self.assertNotContains(response, "Year A Exam")

    def test_exam_submissions_show_attempted_and_not_attempted_students(self):
        ExamAttempt.objects.create(
            exam=self.exam_a,
            academic_session=self.session_a,
            student=self.student,
            submitted_at=timezone.now(),
            score=1,
            total_marks=1,
            correct_count=1,
        )
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:exam_submissions", args=[self.exam_a.pk]))

        self.assertContains(response, "student")
        self.assertContains(response, "student-two")
        self.assertContains(response, "Attempted")
        self.assertContains(response, "Not Attempted")

    def test_bulk_question_template_download_contains_samples(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:exam_question_import_template", args=[self.exam_a.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        workbook = load_workbook(BytesIO(response.content), data_only=True)
        worksheet = workbook.active
        self.assertEqual(worksheet["A1"].value, "Question Text")
        self.assertEqual(worksheet["F1"].value, "Correct Answer")
        self.assertIn(worksheet["F2"].value, {"A", "B", "C", "D"})

    def test_bulk_question_import_creates_questions_options_and_correct_answer(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Question Text", "Option A", "Option B", "Option C", "Option D", "Correct Answer", "Marks"])
        worksheet.append(["2 + 2 equals?", "1", "2", "4", "8", "C", 2])
        worksheet.append(["Unit of force?", "Newton", "Joule", "Watt", "Pascal", "A", 1])
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        upload = SimpleUploadedFile(
            "questions.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(
            reverse("teacher:exam_question_bulk_import", args=[self.exam_a.pk]),
            {"question_file": upload},
        )

        self.assertRedirects(response, reverse("teacher:exam_questions", args=[self.exam_a.pk]))
        self.assertEqual(self.exam_a.questions.count(), 2)
        first_question = ExamQuestion.objects.get(exam=self.exam_a, text="2 + 2 equals?")
        self.assertEqual(first_question.options.count(), 4)
        self.assertEqual(first_question.correct_option.text, "4")
        self.exam_a.refresh_from_db()
        self.assertEqual(self.exam_a.total_marks, 3)

    def test_bulk_question_import_rejects_invalid_correct_answer_without_partial_save(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.append(["Question Text", "Option A", "Option B", "Option C", "Option D", "Correct Answer", "Marks"])
        worksheet.append(["2 + 2 equals?", "1", "2", "4", "8", "E", 1])
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        upload = SimpleUploadedFile(
            "questions.xlsx",
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        response = self.client.post(
            reverse("teacher:exam_question_bulk_import", args=[self.exam_a.pk]),
            {"question_file": upload},
        )

        self.assertRedirects(response, reverse("teacher:exam_questions", args=[self.exam_a.pk]))
        self.assertEqual(self.exam_a.questions.count(), 0)

    def test_question_create_success_closes_popup_window(self):
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(
            reverse("teacher:exam_question_create", args=[self.exam_a.pk]),
            {
                "text": "What is 3 + 3?",
                "marks": "1",
                "options-TOTAL_FORMS": "4",
                "options-INITIAL_FORMS": "0",
                "options-MIN_NUM_FORMS": "0",
                "options-MAX_NUM_FORMS": "4",
                "options-0-text": "4",
                "options-0-is_correct": "",
                "options-1-text": "5",
                "options-1-is_correct": "",
                "options-2-text": "6",
                "options-2-is_correct": "on",
                "options-3-text": "7",
                "options-3-is_correct": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "window.close()")
        self.assertContains(response, reverse("teacher:exam_questions", args=[self.exam_a.pk]))
        self.assertEqual(self.exam_a.questions.count(), 1)

    def test_exam_form_subjects_are_scoped_to_teacher_batch_institute_and_year(self):
        other_institute = Institute.objects.create(name="Other Institute", code="other")
        other_year = AcademicYear.objects.create(
            institute=other_institute,
            name="2026-27",
            start_date="2026-04-01",
            end_date="2027-03-31",
        )
        Subject.objects.create(institute=other_institute, academic_year=other_year, name="Other Physics")

        form = TeacherExamForm(batches=Batch.objects.filter(pk=self.batch_a.pk))

        subject_names = list(form.fields["subject"].queryset.values_list("name", flat=True))
        self.assertEqual(subject_names, ["Physics"])
        rendered = str(form["subject"])
        self.assertIn(f'data-year-id="{self.year_a.pk}"', rendered)

    def test_exam_update_form_keeps_selected_inactive_subject_visible(self):
        self.subject_a.is_active = False
        self.subject_a.save()
        self.exam_a.subject = self.subject_a
        self.exam_a.save()

        form = TeacherExamForm(instance=self.exam_a, batches=Batch.objects.filter(pk=self.batch_a.pk))

        self.assertIn(self.subject_a, form.fields["subject"].queryset)

    def test_teacher_can_publish_and_hide_exam_results_from_submissions(self):
        self.exam_a.show_result_after_submit = False
        self.exam_a.save()
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:exam_submissions", args=[self.exam_a.pk]))

        self.assertContains(response, "Results are hidden")
        self.assertContains(response, "Publish Results")

        response = self.client.post(
            reverse("teacher:exam_toggle_result_publish", args=[self.exam_a.pk]),
            {"action": "publish"},
        )

        self.assertRedirects(response, reverse("teacher:exam_submissions", args=[self.exam_a.pk]))
        self.exam_a.refresh_from_db()
        self.assertTrue(self.exam_a.show_result_after_submit)

        self.client.post(
            reverse("teacher:exam_toggle_result_publish", args=[self.exam_a.pk]),
            {"action": "hide"},
        )
        self.exam_a.refresh_from_db()
        self.assertFalse(self.exam_a.show_result_after_submit)

    def test_teacher_can_publish_exam_from_submissions(self):
        self.exam_a.is_published = False
        self.exam_a.save()
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.get(reverse("teacher:exam_submissions", args=[self.exam_a.pk]))

        self.assertContains(response, "Exam Not Published")
        self.assertContains(response, "Publish Exam")

        response = self.client.post(reverse("teacher:exam_publish", args=[self.exam_a.pk]))

        self.assertRedirects(response, reverse("teacher:exam_submissions", args=[self.exam_a.pk]))
        self.exam_a.refresh_from_db()
        self.assertTrue(self.exam_a.is_published)

    def test_teacher_can_manage_attempt_answer_and_recalculate_score(self):
        question = ExamQuestion.objects.create(exam=self.exam_a, text="2 + 2?", marks=2, order=1)
        wrong_option = ExamQuestionOption.objects.create(question=question, text="3", order=1)
        correct_option = ExamQuestionOption.objects.create(question=question, text="4", order=2, is_correct=True)
        attempt = ExamAttempt.objects.create(
            exam=self.exam_a,
            academic_session=self.session_a,
            student=self.student,
            submitted_at=timezone.now(),
            score=0,
            total_marks=2,
            wrong_count=1,
        )
        ExamQuestionAttempt.objects.create(
            attempt=attempt,
            question=question,
            selected_option=wrong_option,
            is_correct=False,
        )
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(
            reverse("teacher:exam_attempt_manage", args=[self.exam_a.pk, attempt.pk]),
            {f"answer_{question.pk}": str(correct_option.pk), "action": "save_answers"},
        )

        self.assertRedirects(response, reverse("teacher:exam_attempt_manage", args=[self.exam_a.pk, attempt.pk]))
        attempt.refresh_from_db()
        self.assertEqual(attempt.score, 2)
        self.assertEqual(attempt.correct_count, 1)
        self.assertEqual(attempt.wrong_count, 0)
        self.assertEqual(attempt.unattempted_count, 0)
        answer = ExamQuestionAttempt.objects.get(attempt=attempt, question=question)
        self.assertEqual(answer.selected_option, correct_option)
        self.assertTrue(answer.is_correct)
        self.assertTrue(ExamResult.objects.filter(exam=self.exam_a, student=self.student, marks_obtained=2).exists())

    def test_teacher_can_reset_attempt_so_student_can_reattend(self):
        attempt = ExamAttempt.objects.create(
            exam=self.exam_a,
            academic_session=self.session_a,
            student=self.student,
            submitted_at=timezone.now(),
            score=1,
            total_marks=1,
            correct_count=1,
        )
        ExamResult.objects.create(exam=self.exam_a, student=self.student, marks_obtained=1)
        self.client.login(username="teacher", password="pass")
        session = self.client.session
        session["academic_year_id"] = self.year_a.pk
        session.save()

        response = self.client.post(reverse("teacher:exam_attempt_reset", args=[self.exam_a.pk, attempt.pk]))

        self.assertRedirects(response, reverse("teacher:exam_submissions", args=[self.exam_a.pk]))
        self.assertFalse(ExamAttempt.objects.filter(pk=attempt.pk).exists())
        self.assertFalse(ExamResult.objects.filter(exam=self.exam_a, student=self.student).exists())
