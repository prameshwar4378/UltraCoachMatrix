import logging

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from student_parent.models import StudentAcademicSession
from super_admin.models import UserProfile

from .api_serializers import (
    ReportCardAssessmentSerializer,
    ReportCardAssessmentSubjectSerializer,
    ReportCardBulkMarksSaveSerializer,
    ReportCardMarksGridRowSerializer,
    ReportCardStudentResultSerializer,
    ReportCardSubjectResultRowSerializer,
)
from .models import ReportCardAssessmentSubject
from .permissions import (
    MARKS_ENTRY_STATUSES,
    student_can_view_result,
    teacher_can_access_assessment,
    teacher_can_enter_marks,
    teacher_has_subject_allocation,
)
from .selectors import (
    get_active_academic_year_for_request,
    get_teacher_accessible_assessments,
    get_teacher_accessible_assessment_subjects,
    get_completion_summary,
    get_generated_results,
    get_marks_grid,
    get_published_results_for_student,
    get_result_subject_rows,
)
from .services import (
    bulk_save_subject_marks,
)

logger = logging.getLogger(__name__)


def api_response(data=None, *, message="", status_code=200, meta=None):
    payload = {"success": 200 <= status_code < 400}
    if message:
        payload["message"] = message
        payload["detail"] = message
    if data:
        payload.update(data)
    if meta is not None:
        payload["meta"] = meta
    return Response(payload, status=status_code)


def list_response(results, *, meta=None, status_code=200):
    payload = {"success": True, "results": results}
    if meta is not None:
        payload["meta"] = meta
    return Response(payload, status=status_code)


def validation_response(error):
    if isinstance(error, dict):
        return api_response({"errors": error}, message="Validation failed.", status_code=status.HTTP_400_BAD_REQUEST)
    if hasattr(error, "detail"):
        return api_response({"errors": error.detail}, message="Validation failed.", status_code=status.HTTP_400_BAD_REQUEST)
    if hasattr(error, "message_dict"):
        return api_response({"errors": error.message_dict}, message="Validation failed.", status_code=status.HTTP_400_BAD_REQUEST)
    return api_response(message=" ".join(getattr(error, "messages", [str(error)])), status_code=status.HTTP_400_BAD_REQUEST)


def marks_entry_closed_message(assessment):
    return (
        f"Marks entry is not open. Current status: {assessment.get_status_display()}. "
        "Institute admin must open or reopen marks entry before teachers can save marks."
    )


def subject_marks_status(assessment, subject_summary):
    expected_count = subject_summary.get("expected_mark_count", 0)
    entered_count = subject_summary.get("entered_mark_count", 0)
    missing_count = subject_summary.get("missing_mark_count", 0)
    if assessment.status not in MARKS_ENTRY_STATUSES:
        return "CLOSED", "Closed"
    if expected_count == 0 or entered_count == 0:
        return "NOT_STARTED", "Not Started"
    if missing_count == 0:
        return "COMPLETE", "Complete"
    return "IN_PROGRESS", "In Progress"


def attach_teacher_marks_status(assessment, subjects, user):
    summary = get_completion_summary(assessment, assessment_subjects=subjects)
    subject_summary_by_id = {
        item["assessment_subject"].pk: item
        for item in summary.get("subjects", [])
    }
    for subject in subjects:
        subject_summary = subject_summary_by_id.get(subject.pk, {})
        subject.expected_mark_count = subject_summary.get("expected_mark_count", 0)
        subject.entered_mark_count = subject_summary.get("entered_mark_count", 0)
        subject.missing_mark_count = subject_summary.get("missing_mark_count", 0)
        subject.absent_mark_count = subject_summary.get("absent_mark_count", 0)
        subject.marks_status, subject.marks_status_label = subject_marks_status(assessment, subject_summary)
        subject.can_enter_marks = teacher_can_enter_marks(user, assessment, subject)
    assessment.my_subject_count = len(subjects)
    assessment.expected_mark_count = summary.get("expected_mark_count", 0)
    assessment.entered_mark_count = summary.get("entered_mark_count", 0)
    assessment.missing_mark_count = summary.get("missing_mark_count", 0)
    assessment.marks_status, assessment.marks_status_label = subject_marks_status(assessment, summary)
    return summary


def teacher_setup_blocked_response(action):
    return api_response(
        message=f"Teachers cannot {action}. Institute admin manages report-card setup.",
        status_code=status.HTTP_403_FORBIDDEN,
    )


def safe_exception_message(error):
    message = str(error).strip()
    if len(message) > 180:
        message = message[:177] + "..."
    return f"{error.__class__.__name__}: {message or 'No details available'}"


def completion_summary_payload(summary):
    return {
        "student_count": summary["student_count"],
        "subject_count": summary["subject_count"],
        "expected_mark_count": summary["expected_mark_count"],
        "entered_mark_count": summary["entered_mark_count"],
        "missing_mark_count": summary["missing_mark_count"],
        "absent_mark_count": summary["absent_mark_count"],
        "required_expected_mark_count": summary.get("required_expected_mark_count", 0),
        "required_missing_mark_count": summary.get("required_missing_mark_count", 0),
        "is_complete": summary["is_complete"],
        "subjects": [
            {
                "assessment_subject": ReportCardAssessmentSubjectSerializer(item["assessment_subject"]).data,
                "expected_mark_count": item["expected_mark_count"],
                "entered_mark_count": item["entered_mark_count"],
                "missing_mark_count": item["missing_mark_count"],
                "absent_mark_count": item["absent_mark_count"],
                "is_complete": item["is_complete"],
            }
            for item in summary["subjects"]
        ],
    }


class IsTeacherReportCardUser(BasePermission):
    message = "This endpoint is available only for teacher accounts."

    def has_permission(self, request, view):
        profile = getattr(request.user, "profile", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and profile
            and profile.role == UserProfile.Role.TEACHER
            and profile.institute_id
        )


class IsStudentParentReportCardUser(BasePermission):
    message = "This endpoint is available only for student or parent accounts."

    def has_permission(self, request, view):
        profile = getattr(request.user, "profile", None)
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_active
            and profile
            and profile.role == UserProfile.Role.STUDENT_PARENT
        )


class TeacherReportCardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsTeacherReportCardUser]

    def get_assessment(self, assessment_id):
        assessment = get_object_or_404(get_teacher_accessible_assessments(self.request.user), pk=assessment_id)
        if not teacher_can_access_assessment(self.request.user, assessment):
            return None
        return assessment


class TeacherReportCardAssessmentsAPI(TeacherReportCardAPIView):
    def get(self, request):
        academic_year = get_active_academic_year_for_request(request)
        assessments = list(get_teacher_accessible_assessments(request.user, academic_year=academic_year).annotate(
            subject_count=Count("assessment_subjects", distinct=True),
            result_count=Count("student_results", distinct=True),
        ))
        for assessment in assessments:
            subjects = list(get_teacher_accessible_assessment_subjects(request.user, assessment))
            attach_teacher_marks_status(assessment, subjects, request.user)
        return list_response(ReportCardAssessmentSerializer(assessments, many=True).data)

    def post(self, request):
        return teacher_setup_blocked_response("create report-card assessments")


class TeacherReportCardAssessmentDetailAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        subjects = list(get_teacher_accessible_assessment_subjects(request.user, assessment))
        summary = attach_teacher_marks_status(assessment, subjects, request.user)
        results = get_generated_results(assessment)
        return api_response(
            {
                "assessment": ReportCardAssessmentSerializer(assessment).data,
                "subjects": ReportCardAssessmentSubjectSerializer(subjects, many=True).data,
                "results": ReportCardStudentResultSerializer(results, many=True).data,
            },
            meta={"summary": completion_summary_payload(summary)},
        )

    def patch(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("edit report-card assessments")


class TeacherReportCardAssessmentSubjectsAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        subjects = list(get_teacher_accessible_assessment_subjects(request.user, assessment))
        attach_teacher_marks_status(assessment, subjects, request.user)
        return list_response(ReportCardAssessmentSubjectSerializer(subjects, many=True).data)

    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("change assessment subject structure")


class TeacherReportCardAssessmentSubjectDetailAPI(TeacherReportCardAPIView):
    def get_subject(self, assessment, assessment_subject_id):
        return get_object_or_404(
            ReportCardAssessmentSubject.objects.select_related("assessment", "subject"),
            assessment=assessment,
            pk=assessment_subject_id,
        )

    def patch(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("change assessment subject structure")

    def delete(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("change assessment subject structure")


class TeacherReportCardMarksGridAPI(TeacherReportCardAPIView):
    def get_subject(self, assessment, assessment_subject_id):
        assessment_subject = get_object_or_404(ReportCardAssessmentSubject, assessment=assessment, pk=assessment_subject_id)
        if not teacher_has_subject_allocation(self.request.user, assessment_subject):
            return None
        return assessment_subject

    def get(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        if not assessment_subject:
            return api_response(message="You can access only your allocated report-card subject.", status_code=status.HTTP_403_FORBIDDEN)
        try:
            grid = get_marks_grid(assessment_subject)
            return api_response(
                {
                    "subject": ReportCardAssessmentSubjectSerializer(assessment_subject).data,
                    "rows": ReportCardMarksGridRowSerializer(grid, many=True).data,
                }
            )
        except Exception as error:
            logger.exception(
                "Report-card API marks grid failed for assessment_id=%s assessment_subject_id=%s user_id=%s",
                assessment_id,
                assessment_subject_id,
                request.user.pk,
            )
            return api_response(
                message=f"Unable to load report-card marks grid. Technical reason: {safe_exception_message(error)}.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    def post(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        if not assessment_subject:
            return api_response(message="You can save marks only for your allocated report-card subject.", status_code=status.HTTP_403_FORBIDDEN)
        if not teacher_can_enter_marks(request.user, assessment, assessment_subject):
            if assessment.status not in MARKS_ENTRY_STATUSES:
                return api_response(message=marks_entry_closed_message(assessment), status_code=status.HTTP_403_FORBIDDEN)
            return api_response(message="You can save marks only for your allocated report-card subject.", status_code=status.HTTP_403_FORBIDDEN)
        serializer = ReportCardBulkMarksSaveSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        try:
            saved = bulk_save_subject_marks(assessment_subject, serializer.validated_data["rows"], actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        except Exception as error:
            logger.exception(
                "Report-card API marks save failed for assessment_id=%s assessment_subject_id=%s user_id=%s",
                assessment_id,
                assessment_subject_id,
                request.user.pk,
            )
            return api_response(
                message=f"Unable to save report-card marks. Technical reason: {safe_exception_message(error)}.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return api_response({"saved_count": len(saved)}, message="Marks saved.")


class TeacherReportCardCompletionAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        subjects = get_teacher_accessible_assessment_subjects(request.user, assessment)
        return api_response({"summary": completion_summary_payload(get_completion_summary(assessment, assessment_subjects=subjects))})


class TeacherReportCardGenerateAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("generate report-card results")


class TeacherReportCardPublishAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("publish report-card results")


class TeacherReportCardLockAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return teacher_setup_blocked_response("lock report-card assessments")


class StudentReportCardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudentParentReportCardUser]

    def get_student(self, request):
        return getattr(request.user, "student_profile", None)

    def get_active_student_session(self, student):
        if not student:
            return None
        academic_year = get_active_academic_year_for_request(self.request, institute=getattr(student, "institute", None))
        sessions = student.academic_sessions.filter(
            status=StudentAcademicSession.Status.ACTIVE,
        ).select_related("academic_year", "institute")
        if academic_year:
            sessions = sessions.filter(academic_year=academic_year)
        return sessions.order_by("-academic_year__start_date", "-pk").first()


class StudentReportCardsAPI(StudentReportCardAPIView):
    def get(self, request):
        student = self.get_student(request)
        if not student:
            return api_response(message="No student profile is linked to this user.", status_code=status.HTTP_404_NOT_FOUND)
        results = get_published_results_for_student(student, academic_session=self.get_active_student_session(student))
        return list_response(ReportCardStudentResultSerializer(results, many=True).data)


class StudentReportCardDetailAPI(StudentReportCardAPIView):
    def get(self, request, result_id):
        student = self.get_student(request)
        if not student:
            return api_response(message="No student profile is linked to this user.", status_code=status.HTTP_404_NOT_FOUND)
        result = get_object_or_404(
            get_published_results_for_student(student, academic_session=self.get_active_student_session(student)),
            pk=result_id,
        )
        if not student_can_view_result(request.user, result):
            return api_response(message="This report card is not available.", status_code=status.HTTP_403_FORBIDDEN)
        subject_rows = get_result_subject_rows(result)
        return api_response(
            {
                "result": ReportCardStudentResultSerializer(result).data,
                "subjects": ReportCardSubjectResultRowSerializer(subject_rows, many=True).data,
            }
        )
