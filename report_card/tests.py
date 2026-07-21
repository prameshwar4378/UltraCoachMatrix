from datetime import date
from decimal import Decimal
import json

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from institute_admin.models import AcademicYear, Batch, Course, Subject
from report_card.forms import ReportCardAssessmentForm, ReportCardAssessmentSubjectForm, ReportCardGradeRuleForm
from report_card.models import (
    ReportCardAssessment,
    ReportCardAssessmentSubject,
    ReportCardAssessmentSubjectComponent,
    ReportCardComponentMarkEntry,
    ReportCardGradeRule,
    ReportCardMarkEntry,
    ReportCardSubjectResult,
    ReportCardStudentResult,
)
from report_card.permissions import student_can_view_result, teacher_can_edit_assessment
from report_card.selectors import get_assessments_for_teacher, get_completion_summary, get_published_results_for_student
from report_card.services import (
    add_assessment_subject,
    add_assessment_subject_component,
    bulk_save_subject_marks,
    create_assessment,
    generate_assessment_results,
    lock_assessment,
    open_marks_entry,
    publish_assessment_results,
    sync_assessment_subject_components,
    update_assessment,
)
from student_parent.models import StudentAcademicSession, StudentEnrollment, StudentProfile
from super_admin.models import Institute, UserProfile
from teacher.models import Exam, ExamResult, TeacherProfile


class ReportCardFeatureTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(name="Report Institute", code="report")
        self.other_institute = Institute.objects.create(name="Other Institute", code="other-report")
        self.year = AcademicYear.objects.create(
            institute=self.institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.other_year = AcademicYear.objects.create(
            institute=self.other_institute,
            name="2026-27",
            start_date=date(2026, 4, 1),
            end_date=date(2027, 3, 31),
        )
        self.next_year = AcademicYear.objects.create(
            institute=self.institute,
            name="2027-28",
            start_date=date(2027, 4, 1),
            end_date=date(2028, 3, 31),
        )

        self.teacher = User.objects.create_user(username="report-teacher", password="pass")
        UserProfile.objects.create(
            user=self.teacher,
            institute=self.institute,
            role=UserProfile.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(username="other-report-teacher", password="pass")
        UserProfile.objects.create(
            user=self.other_teacher,
            institute=self.institute,
            role=UserProfile.Role.TEACHER,
        )

        self.course = Course.objects.create(institute=self.institute, academic_year=self.year, name="Class 8")
        self.batch = Batch.objects.create(institute=self.institute, academic_year=self.year, name="8-A")
        self.batch.courses.add(self.course)
        self.batch.teachers.add(self.teacher)
        self.unassigned_batch = Batch.objects.create(
            institute=self.institute,
            academic_year=self.year,
            name="8-B",
        )
        self.unassigned_batch.courses.add(self.course)
        self.unassigned_batch.teachers.add(self.other_teacher)

        self.math = Subject.objects.create(institute=self.institute, academic_year=self.year, name="Mathematics")
        self.science = Subject.objects.create(institute=self.institute, academic_year=self.year, name="Science")
        self.art = Subject.objects.create(institute=self.institute, academic_year=self.year, name="Art")
        self.other_subject = Subject.objects.create(
            institute=self.other_institute,
            academic_year=self.other_year,
            name="Other Science",
        )
        self.next_year_subject = Subject.objects.create(
            institute=self.institute,
            academic_year=self.next_year,
            name="Future Math",
        )

        self.session_1 = self._create_student("student-one", "A001", "Ada", "Lovelace", "1")
        self.session_2 = self._create_student("student-two", "A002", "Grace", "Hopper", "2")
        self.session_3 = self._create_student("student-three", "A003", "Katherine", "Johnson", "3")

    def _create_student(self, username, admission_number, first_name, last_name, roll_number):
        user = User.objects.create_user(
            username=username,
            password="pass",
            first_name=first_name,
            last_name=last_name,
        )
        UserProfile.objects.create(
            user=user,
            institute=self.institute,
            role=UserProfile.Role.STUDENT_PARENT,
        )
        student = StudentProfile.objects.create(
            institute=self.institute,
            academic_year=self.year,
            user=user,
            admission_number=admission_number,
            roll_number=roll_number,
        )
        session = StudentAcademicSession.objects.create(
            institute=self.institute,
            student=student,
            academic_year=self.year,
            admission_number=admission_number,
        )
        enrollment = StudentEnrollment.objects.create(
            student=student,
            academic_session=session,
            batch=self.batch,
        )
        enrollment.courses.add(self.course)
        return session

    def _assessment(self, title="Mid Term"):
        return create_assessment(
            institute=self.institute,
            academic_year=self.year,
            batch=self.batch,
            title=title,
            created_by=self.teacher,
        )

    def _subject(self, assessment, subject=None, **kwargs):
        defaults = {
            "subject": subject or self.math,
            "max_marks": Decimal("100"),
            "passing_marks": Decimal("35"),
            "weightage": Decimal("100"),
            "display_order": assessment.assessment_subjects.count() + 1,
            "actor": self.teacher,
        }
        defaults.update(kwargs)
        return add_assessment_subject(assessment, **defaults)

    def _open_and_save(self, assessment_subject, rows):
        assessment = assessment_subject.assessment
        if assessment.status != ReportCardAssessment.Status.MARKS_ENTRY_OPEN:
            open_marks_entry(assessment, actor=self.teacher)
            assessment.refresh_from_db()
        return bulk_save_subject_marks(assessment_subject, rows, actor=self.teacher)

    def test_report_card_assessment_creation_does_not_create_or_modify_teacher_exam(self):
        exam = Exam.objects.create(
            academic_year=self.year,
            batch=self.batch,
            course=self.course,
            subject=self.math,
            title="Online Unit Test",
            exam_date=date(2026, 7, 1),
            total_marks=20,
            created_by=self.teacher,
        )
        before = list(Exam.objects.values("id", "title", "total_marks", "is_published"))

        assessment = self._assessment()

        self.assertEqual(Exam.objects.count(), 1)
        self.assertEqual(list(Exam.objects.values("id", "title", "total_marks", "is_published")), before)
        self.assertNotEqual(assessment.title, exam.title)

    def test_report_card_result_generation_does_not_create_or_modify_teacher_exam_result(self):
        exam = Exam.objects.create(
            academic_year=self.year,
            batch=self.batch,
            course=self.course,
            subject=self.math,
            title="Online Final",
            exam_date=date(2026, 8, 1),
            total_marks=50,
            created_by=self.teacher,
        )
        ExamResult.objects.create(
            exam=exam,
            student=self.session_1.student,
            marks_obtained=Decimal("44"),
            remark="Online result remains separate.",
        )
        before = list(ExamResult.objects.values("id", "exam_id", "student_id", "marks_obtained", "remark"))
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "80"},
                {"academic_session": self.session_2, "marks_obtained": "70"},
                {"academic_session": self.session_3, "marks_obtained": "60"},
            ],
        )

        generate_assessment_results(assessment, actor=self.teacher)

        self.assertEqual(ExamResult.objects.count(), 1)
        self.assertEqual(list(ExamResult.objects.values("id", "exam_id", "student_id", "marks_obtained", "remark")), before)

    def test_teacher_sees_only_assigned_batch_assessments(self):
        assigned = self._assessment("Assigned Assessment")
        unassigned = create_assessment(
            institute=self.institute,
            academic_year=self.year,
            batch=self.unassigned_batch,
            title="Unassigned Assessment",
            created_by=self.other_teacher,
        )

        assessments = list(get_assessments_for_teacher(self.teacher, academic_year=self.year))

        self.assertIn(assigned, assessments)
        self.assertNotIn(unassigned, assessments)

    def test_teacher_profile_institute_is_used_for_report_card_scoping(self):
        self.teacher.profile.institute = self.other_institute
        self.teacher.profile.save(update_fields=["institute"])
        TeacherProfile.objects.create(user=self.teacher, institute=self.institute)
        assessment = self._assessment("Teacher Profile Scoped")

        assessments = list(get_assessments_for_teacher(self.teacher, academic_year=self.year))

        self.assertIn(assessment, assessments)
        self.assertTrue(teacher_can_edit_assessment(self.teacher, assessment))

    def test_assigned_batch_institute_is_used_when_user_profile_institute_is_stale(self):
        self.teacher.profile.institute = self.other_institute
        self.teacher.profile.save(update_fields=["institute"])
        assessment = self._assessment("Assigned Batch Scoped")
        form = ReportCardAssessmentForm(
            data={
                "academic_year": self.year.pk,
                "batch": self.batch.pk,
                "title": "Mid Term",
                "assessment_date": "2026-07-19",
                "result_date": "2026-07-21",
            },
            user=self.teacher,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.effective_institute, self.institute)
        self.assertIn(assessment, list(get_assessments_for_teacher(self.teacher, academic_year=self.year)))

    def test_batch_and_subject_fk_validation_works(self):
        with self.assertRaises(ValidationError):
            create_assessment(
                institute=self.institute,
                academic_year=self.year,
                batch=Batch.objects.create(
                    institute=self.institute,
                    academic_year=self.next_year,
                    name="Future Batch",
                ),
                title="Wrong Batch Year",
                created_by=self.teacher,
            )

        assessment = self._assessment()
        with self.assertRaises(ValidationError):
            self._subject(assessment, subject=self.other_subject)
        with self.assertRaises(ValidationError):
            self._subject(assessment, subject=self.next_year_subject)

    def test_snapshot_fields_are_copied_correctly(self):
        assessment = self._assessment()
        subject = self._subject(assessment, self.math)
        self._open_and_save(subject, [{"academic_session": self.session_1, "marks_obtained": "78"}])
        mark = ReportCardMarkEntry.objects.get(assessment_subject=subject, academic_session=self.session_1)

        self.assertEqual(assessment.institute_name_snapshot, self.institute.name)
        self.assertEqual(assessment.academic_year_name_snapshot, self.year.name)
        self.assertEqual(assessment.batch_name_snapshot, self.batch.name)
        self.assertEqual(subject.subject_name_snapshot, self.math.name)
        self.assertEqual(mark.student_name_snapshot, "Ada Lovelace")
        self.assertEqual(mark.admission_number_snapshot, "A001")

    def test_different_subjects_per_assessment_work(self):
        first = self._assessment("Term One")
        second = self._assessment("Term Two")
        first_math = self._subject(first, self.math)
        first_science = self._subject(first, self.science)
        second_art = self._subject(second, self.art)

        self.assertEqual(set(first.assessment_subjects.values_list("subject_id", flat=True)), {self.math.pk, self.science.pk})
        self.assertEqual(list(second.assessment_subjects.values_list("subject_id", flat=True)), [self.art.pk])
        self.assertNotEqual(first_math.pk, second_art.pk)
        self.assertNotEqual(first_science.subject_id, second_art.subject_id)

    def test_different_max_marks_and_weightage_work(self):
        assessment = self._assessment()
        math = self._subject(
            assessment,
            self.math,
            max_marks=Decimal("50"),
            passing_marks=Decimal("18"),
            weightage=Decimal("50"),
        )
        science = self._subject(
            assessment,
            self.science,
            max_marks=Decimal("100"),
            passing_marks=Decimal("35"),
            weightage=Decimal("150"),
        )
        open_marks_entry(assessment, actor=self.teacher)
        bulk_save_subject_marks(math, [{"academic_session": self.session_1, "marks_obtained": "45"}], actor=self.teacher)
        bulk_save_subject_marks(science, [{"academic_session": self.session_1, "marks_obtained": "60"}], actor=self.teacher)

        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]

        self.assertEqual(result.total_obtained, Decimal("105.00"))
        self.assertEqual(result.total_max_marks, Decimal("150.00"))
        self.assertEqual(result.total_weightage, Decimal("200.00"))
        self.assertEqual(result.percentage, Decimal("67.50"))

    def test_bulk_marks_save_creates_and_updates_marks_correctly(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "76", "remark": "Initial"},
                {"academic_session": self.session_2, "marks_obtained": "66"},
            ],
        )
        self.assertEqual(ReportCardMarkEntry.objects.filter(assessment_subject=math).count(), 2)

        bulk_save_subject_marks(
            math,
            [{"academic_session": self.session_1, "marks_obtained": "88", "remark": "Updated"}],
            actor=self.teacher,
        )
        entry = ReportCardMarkEntry.objects.get(assessment_subject=math, academic_session=self.session_1)

        self.assertEqual(ReportCardMarkEntry.objects.filter(assessment_subject=math).count(), 2)
        self.assertEqual(entry.marks_obtained, Decimal("88.00"))
        self.assertEqual(entry.remark, "Updated")

    def test_bulk_marks_save_allows_partial_single_column_marks(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "76"},
                {"academic_session": self.session_2, "marks_obtained": ""},
            ],
        )

        blank_entry = ReportCardMarkEntry.objects.get(assessment_subject=math, academic_session=self.session_2)
        summary = get_completion_summary(assessment)

        self.assertIsNone(blank_entry.marks_obtained)
        self.assertEqual(summary["entered_mark_count"], 1)
        self.assertEqual(summary["missing_mark_count"], 2)
        self.assertFalse(summary["is_complete"])

    def test_bulk_marks_save_allows_partial_component_marks(self):
        assessment = self._assessment()
        math = self._subject(assessment, max_marks=Decimal("60"), passing_marks=Decimal("21"))
        theory = add_assessment_subject_component(
            math,
            name="Theory Exam",
            max_marks=Decimal("50"),
            weightage=Decimal("50"),
            display_order=1,
            actor=self.teacher,
        )
        viva = add_assessment_subject_component(
            math,
            name="Viva",
            max_marks=Decimal("10"),
            weightage=Decimal("10"),
            display_order=2,
            actor=self.teacher,
        )
        self._open_and_save(
            math,
            [
                {
                    "academic_session": self.session_1,
                    "component_marks": {theory.pk: "40", viva.pk: ""},
                }
            ],
        )

        subject_entry = ReportCardMarkEntry.objects.get(assessment_subject=math, academic_session=self.session_1)
        theory_entry = ReportCardComponentMarkEntry.objects.get(component=theory, academic_session=self.session_1)
        viva_entry = ReportCardComponentMarkEntry.objects.get(component=viva, academic_session=self.session_1)
        summary = get_completion_summary(assessment)

        self.assertIsNone(subject_entry.marks_obtained)
        self.assertEqual(theory_entry.marks_obtained, Decimal("40.00"))
        self.assertIsNone(viva_entry.marks_obtained)
        self.assertEqual(summary["entered_mark_count"], 1)
        self.assertEqual(summary["missing_mark_count"], 5)
        self.assertFalse(summary["is_complete"])

    def test_marks_above_max_and_negative_marks_are_rejected(self):
        assessment = self._assessment()
        math = self._subject(assessment, max_marks=Decimal("50"), passing_marks=Decimal("18"))
        open_marks_entry(assessment, actor=self.teacher)

        with self.assertRaises(ValidationError):
            bulk_save_subject_marks(
                math,
                [{"academic_session": self.session_1, "marks_obtained": "51"}],
                actor=self.teacher,
            )
        with self.assertRaises(ValidationError):
            bulk_save_subject_marks(
                math,
                [{"academic_session": self.session_1, "marks_obtained": "-1"}],
                actor=self.teacher,
            )

        self.assertFalse(ReportCardMarkEntry.objects.filter(assessment_subject=math).exists())

    def test_absent_students_are_handled_correctly(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(math, [{"academic_session": self.session_1, "is_absent": True}])

        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]

        self.assertEqual(result.result_status, ReportCardStudentResult.ResultStatus.ABSENT)
        self.assertIsNone(result.percentage)

    def test_include_in_total_false_subjects_are_excluded_from_percentage(self):
        assessment = self._assessment()
        math = self._subject(assessment, self.math, max_marks=Decimal("50"), passing_marks=Decimal("18"))
        art = self._subject(
            assessment,
            self.art,
            max_marks=Decimal("100"),
            passing_marks=Decimal("0"),
            include_in_total=False,
        )
        open_marks_entry(assessment, actor=self.teacher)
        bulk_save_subject_marks(math, [{"academic_session": self.session_1, "marks_obtained": "50"}], actor=self.teacher)
        bulk_save_subject_marks(art, [{"academic_session": self.session_1, "marks_obtained": "10"}], actor=self.teacher)

        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]

        self.assertEqual(result.total_obtained, Decimal("50.00"))
        self.assertEqual(result.total_max_marks, Decimal("50.00"))
        self.assertEqual(result.percentage, Decimal("100.00"))

    def test_optional_subjects_work_correctly(self):
        assessment = self._assessment()
        math = self._subject(assessment, self.math)
        self._subject(assessment, self.art, is_optional=True, display_order=2)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "75"},
                {"academic_session": self.session_2, "marks_obtained": "70"},
                {"academic_session": self.session_3, "marks_obtained": "65"},
            ],
        )

        results = generate_assessment_results(assessment, actor=self.teacher)

        self.assertEqual(len(results), 3)
        self.assertFalse(any(result.result_status == ReportCardStudentResult.ResultStatus.INCOMPLETE for result in results))

    def test_passing_marks_affect_pass_fail(self):
        assessment = self._assessment()
        math = self._subject(assessment, self.math, passing_marks=Decimal("35"))
        self._open_and_save(math, [{"academic_session": self.session_1, "marks_obtained": "34"}])

        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]

        self.assertEqual(result.result_status, ReportCardStudentResult.ResultStatus.FAIL)
        self.assertIsNone(result.rank)

    def test_grade_rules_apply_correctly(self):
        ReportCardGradeRule.objects.create(
            institute=self.institute,
            academic_year=self.year,
            min_percentage=Decimal("80"),
            max_percentage=Decimal("100"),
            grade="A",
            remark="Excellent",
        )
        ReportCardGradeRule.objects.create(
            institute=self.institute,
            academic_year=self.year,
            min_percentage=Decimal("0"),
            max_percentage=Decimal("79.99"),
            grade="B",
        )
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(math, [{"academic_session": self.session_1, "marks_obtained": "88"}])

        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]

        self.assertEqual(result.grade, "A")
        self.assertEqual(result.remark, "Excellent")

    def test_grade_rule_form_accepts_matching_academic_year(self):
        form = ReportCardGradeRuleForm(
            data={
                "academic_year": self.year.pk,
                "min_percentage": "91",
                "max_percentage": "100",
                "grade": "A++",
                "remark": "A++",
                "display_order": "1",
                "is_active": "on",
            },
            institute=self.institute,
        )

        self.assertTrue(form.is_valid(), form.errors.as_text())
        rule = form.save()
        self.assertEqual(rule.institute, self.institute)
        self.assertEqual(rule.academic_year, self.year)

    def test_grade_rule_form_handles_missing_percentage_without_crashing(self):
        form = ReportCardGradeRuleForm(
            data={
                "academic_year": self.year.pk,
                "min_percentage": "91",
                "max_percentage": "",
                "grade": "A++",
                "remark": "A++",
                "display_order": "1",
                "is_active": "on",
            },
            institute=self.institute,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("max_percentage", form.errors)

    def test_custom_subject_components_generate_subject_grade(self):
        ReportCardGradeRule.objects.create(
            institute=self.institute,
            academic_year=self.year,
            min_percentage=Decimal("90"),
            max_percentage=Decimal("100"),
            grade="A1",
        )
        ReportCardGradeRule.objects.create(
            institute=self.institute,
            academic_year=self.year,
            min_percentage=Decimal("70"),
            max_percentage=Decimal("89.99"),
            grade="B1",
        )
        assessment = self._assessment()
        english = self._subject(assessment, self.math, max_marks=Decimal("100"), passing_marks=Decimal("0"))
        unit = add_assessment_subject_component(
            english,
            name="Unit Test",
            max_marks=Decimal("10"),
            passing_marks=Decimal("0"),
            display_order=1,
            actor=self.teacher,
        )
        notebook = add_assessment_subject_component(
            english,
            name="Notebook",
            max_marks=Decimal("10"),
            passing_marks=Decimal("0"),
            display_order=2,
            actor=self.teacher,
        )
        theory = add_assessment_subject_component(
            english,
            name="Theory",
            max_marks=Decimal("80"),
            passing_marks=Decimal("0"),
            display_order=3,
            actor=self.teacher,
        )
        open_marks_entry(assessment, actor=self.teacher)

        bulk_save_subject_marks(
            english,
            [
                {
                    "academic_session": self.session_1,
                    "component_marks": {
                        unit.pk: "10",
                        notebook.pk: "9",
                        theory.pk: "75",
                    },
                }
            ],
            actor=self.teacher,
        )
        result = generate_assessment_results(assessment, actor=self.teacher, require_complete=False)[0]
        subject_result = ReportCardSubjectResult.objects.get(result=result, assessment_subject=english)

        self.assertEqual(subject_result.obtained_marks, Decimal("94.00"))
        self.assertEqual(subject_result.percentage, Decimal("94.00"))
        self.assertEqual(subject_result.grade, "A1")
        self.assertEqual(result.total_obtained, Decimal("94.00"))
        self.assertEqual(ReportCardAssessmentSubjectComponent.objects.filter(assessment_subject=english).count(), 3)

    def test_subject_form_saves_local_additional_columns_on_submit(self):
        assessment = self._assessment()
        components = [
            {
                "id": None,
                "name": "Notebook",
                "max_marks": "10",
                "passing_marks": "999",
                "weightage": "999",
                "display_order": 1,
                "include_in_total": True,
            },
            {
                "id": None,
                "name": "Theory",
                "max_marks": "90",
                "passing_marks": "999",
                "weightage": "999",
                "display_order": 2,
                "include_in_total": True,
            },
        ]
        form = ReportCardAssessmentSubjectForm(
            data={
                "subject": self.math.pk,
                "max_marks": "100",
                "passing_marks": "0",
                "weightage": "100",
                "display_order": "1",
                "is_optional": "",
                "include_in_total": "on",
                "components_json": json.dumps(components),
            },
            assessment=assessment,
        )

        self.assertTrue(form.is_valid(), form.errors)
        assessment_subject = add_assessment_subject(
            assessment,
            subject=form.cleaned_data["subject"],
            max_marks=form.cleaned_data["max_marks"],
            passing_marks=form.cleaned_data["passing_marks"],
            weightage=form.cleaned_data["weightage"],
            display_order=form.cleaned_data["display_order"],
            is_optional=form.cleaned_data["is_optional"],
            include_in_total=form.cleaned_data["include_in_total"],
            actor=self.teacher,
        )
        sync_assessment_subject_components(
            assessment_subject,
            form.cleaned_data["components"],
            actor=self.teacher,
        )

        self.assertEqual(
            list(assessment_subject.components.values_list("name_snapshot", "max_marks", "weightage")),
            [("Notebook", Decimal("10.00"), Decimal("10.00")), ("Theory", Decimal("90.00"), Decimal("90.00"))],
        )
        self.assertEqual(
            list(assessment_subject.components.values_list("passing_marks", flat=True)),
            [Decimal("0.00"), Decimal("0.00")],
        )

    def test_subject_display_order_is_assigned_automatically(self):
        assessment = self._assessment()
        first = self._subject(assessment, self.math)
        form = ReportCardAssessmentSubjectForm(
            data={
                "subject": self.science.pk,
                "passing_marks": "30",
                "is_optional": "",
                "include_in_total": "on",
                "components_json": json.dumps(
                    [
                        {
                            "name": "Theory Exam",
                            "max_marks": "80",
                            "include_in_total": True,
                        }
                    ]
                ),
            },
            assessment=assessment,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["display_order"], first.display_order + 1)

    def test_subject_passing_marks_cannot_exceed_additional_column_total(self):
        assessment = self._assessment()
        form = ReportCardAssessmentSubjectForm(
            data={
                "subject": self.math.pk,
                "max_marks": "80",
                "passing_marks": "81",
                "weightage": "100",
                "display_order": "1",
                "is_optional": "",
                "include_in_total": "on",
                "components_json": json.dumps(
                    [
                        {
                            "name": "Notebook",
                            "max_marks": "10",
                            "display_order": 1,
                            "include_in_total": True,
                        },
                        {
                            "name": "Theory",
                            "max_marks": "70",
                            "display_order": 2,
                            "include_in_total": True,
                        },
                    ]
                ),
            },
            assessment=assessment,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("passing_marks", form.errors)

    def test_subject_form_can_be_edited_after_marks_entry_opens(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        open_marks_entry(assessment, actor=self.teacher)
        assessment.refresh_from_db()

        form = ReportCardAssessmentSubjectForm(
            data={
                "subject": self.math.pk,
                "max_marks": "80",
                "passing_marks": "30",
                "weightage": "100",
                "display_order": "1",
                "is_optional": "",
                "include_in_total": "on",
                "components_json": json.dumps(
                    [
                        {
                            "name": "Theory Exam",
                            "max_marks": "80",
                            "display_order": 1,
                            "include_in_total": True,
                        }
                    ]
                ),
            },
            instance=math,
            assessment=assessment,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_rank_generation_works(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "80"},
                {"academic_session": self.session_2, "marks_obtained": "95"},
                {"academic_session": self.session_3, "marks_obtained": "80"},
            ],
        )

        generate_assessment_results(assessment, actor=self.teacher)
        ranks = {
            result.admission_number_snapshot: result.rank
            for result in ReportCardStudentResult.objects.filter(assessment=assessment)
        }

        self.assertEqual(ranks["A002"], 1)
        self.assertEqual(ranks["A001"], 2)
        self.assertEqual(ranks["A003"], 2)

    def test_published_results_are_visible_and_unpublished_results_are_hidden(self):
        assessment = self._assessment("Visible Term")
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "80"},
                {"academic_session": self.session_2, "marks_obtained": "70"},
                {"academic_session": self.session_3, "marks_obtained": "60"},
            ],
        )
        generated = generate_assessment_results(assessment, actor=self.teacher)
        unpublished_result = next(result for result in generated if result.academic_session_id == self.session_1.pk)

        self.assertFalse(student_can_view_result(self.session_1.student.user, unpublished_result))
        self.assertEqual(list(get_published_results_for_student(self.session_1.student)), [])

        publish_assessment_results(assessment, actor=self.teacher)
        unpublished_result.refresh_from_db()

        self.assertTrue(student_can_view_result(self.session_1.student.user, unpublished_result))
        self.assertEqual(list(get_published_results_for_student(self.session_1.student)), [unpublished_result])

    def test_locked_assessments_cannot_be_edited_by_teacher(self):
        assessment = self._assessment()
        math = self._subject(assessment)
        self._open_and_save(
            math,
            [
                {"academic_session": self.session_1, "marks_obtained": "80"},
                {"academic_session": self.session_2, "marks_obtained": "70"},
                {"academic_session": self.session_3, "marks_obtained": "60"},
            ],
        )
        generate_assessment_results(assessment, actor=self.teacher)
        publish_assessment_results(assessment, actor=self.teacher)
        lock_assessment(assessment, actor=self.teacher)
        assessment.refresh_from_db()

        self.assertFalse(teacher_can_edit_assessment(self.teacher, assessment))
        with self.assertRaises(ValidationError):
            update_assessment(assessment, actor=self.teacher, title="Changed after lock")
        with self.assertRaises(ValidationError):
            bulk_save_subject_marks(
                math,
                [{"academic_session": self.session_1, "marks_obtained": "90"}],
                actor=self.teacher,
            )
