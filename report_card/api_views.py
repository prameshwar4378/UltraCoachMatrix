from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from institute_admin.models import AcademicYear, Subject
from super_admin.models import UserProfile

from .api_serializers import (
    ReportCardAssessmentSerializer,
    ReportCardAssessmentSubjectSerializer,
    ReportCardAssessmentSubjectUpdateSerializer,
    ReportCardAssessmentSubjectWriteSerializer,
    ReportCardAssessmentUpdateSerializer,
    ReportCardAssessmentWriteSerializer,
    ReportCardBulkMarksSaveSerializer,
    ReportCardMarksGridRowSerializer,
    ReportCardStudentResultSerializer,
    ReportCardSubjectResultRowSerializer,
)
from .models import ReportCardAssessmentSubject
from .permissions import (
    student_can_view_result,
    teacher_can_access_assessment,
    teacher_can_edit_assessment,
    teacher_can_enter_marks,
)
from .selectors import (
    get_assessment_subjects,
    get_assessments_for_teacher,
    get_completion_summary,
    get_generated_results,
    get_marks_grid,
    get_published_results_for_student,
    get_result_subject_rows,
    get_teacher_assigned_batches,
    get_teacher_institute,
)
from .services import (
    add_assessment_subject,
    bulk_save_subject_marks,
    create_assessment,
    generate_assessment_results,
    lock_assessment,
    publish_assessment_results,
    remove_assessment_subject,
    update_assessment,
    update_assessment_subject,
    validate_marks_completion,
)


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
        assessment = get_object_or_404(get_assessments_for_teacher(self.request.user), pk=assessment_id)
        if not teacher_can_access_assessment(self.request.user, assessment):
            return None
        return assessment


class TeacherReportCardAssessmentsAPI(TeacherReportCardAPIView):
    def get(self, request):
        academic_year_id = request.query_params.get("academic_year_id")
        academic_year = None
        if academic_year_id:
            institute = get_teacher_institute(request.user)
            academic_year = get_object_or_404(AcademicYear, pk=academic_year_id, institute=institute)
        assessments = get_assessments_for_teacher(request.user, academic_year=academic_year).annotate(
            subject_count=Count("assessment_subjects", distinct=True),
            result_count=Count("student_results", distinct=True),
        )
        return list_response(ReportCardAssessmentSerializer(assessments, many=True).data)

    def post(self, request):
        serializer = ReportCardAssessmentWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        data = serializer.validated_data
        institute = get_teacher_institute(request.user)
        academic_year = get_object_or_404(AcademicYear, pk=data["academic_year_id"], institute=institute)
        batch = get_teacher_assigned_batches(request.user, academic_year=academic_year).filter(pk=data["batch_id"]).first()
        if not batch:
            return api_response(message="Class not found.", status_code=status.HTTP_404_NOT_FOUND)
        try:
            assessment = create_assessment(
                institute=institute,
                academic_year=academic_year,
                batch=batch,
                title=data["title"],
                assessment_date=data.get("assessment_date"),
                result_date=data.get("result_date"),
                created_by=request.user,
            )
        except ValidationError as error:
            return validation_response(error)
        return api_response(
            {"assessment": ReportCardAssessmentSerializer(assessment).data},
            message="Assessment created.",
            status_code=status.HTTP_201_CREATED,
        )


class TeacherReportCardAssessmentDetailAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        subjects = get_assessment_subjects(assessment)
        results = get_generated_results(assessment)
        return api_response(
            {
                "assessment": ReportCardAssessmentSerializer(assessment).data,
                "subjects": ReportCardAssessmentSubjectSerializer(subjects, many=True).data,
                "results": ReportCardStudentResultSerializer(results, many=True).data,
            }
        )

    def patch(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot edit this assessment.", status_code=status.HTTP_403_FORBIDDEN)
        serializer = ReportCardAssessmentUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        data = serializer.validated_data
        fields = {}
        if "academic_year_id" in data:
            fields["academic_year"] = get_object_or_404(AcademicYear, pk=data["academic_year_id"], institute=assessment.institute)
        if "batch_id" in data:
            academic_year = fields.get("academic_year", assessment.academic_year)
            batch = get_teacher_assigned_batches(request.user, academic_year=academic_year).filter(pk=data["batch_id"]).first()
            if not batch:
                return api_response(message="Class not found.", status_code=status.HTTP_404_NOT_FOUND)
            fields["batch"] = batch
        for field in ("title", "assessment_date", "result_date"):
            if field in data:
                fields[field] = data[field]
        try:
            assessment = update_assessment(assessment, actor=request.user, **fields)
        except ValidationError as error:
            return validation_response(error)
        return api_response({"assessment": ReportCardAssessmentSerializer(assessment).data}, message="Assessment updated.")


class TeacherReportCardAssessmentSubjectsAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        subjects = get_assessment_subjects(assessment)
        return list_response(ReportCardAssessmentSubjectSerializer(subjects, many=True).data)

    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot change this assessment structure.", status_code=status.HTTP_403_FORBIDDEN)
        serializer = ReportCardAssessmentSubjectWriteSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        data = serializer.validated_data
        subject = get_object_or_404(Subject, pk=data["subject_id"], institute=assessment.institute, academic_year=assessment.academic_year)
        try:
            assessment_subject = add_assessment_subject(
                assessment,
                subject=subject,
                max_marks=data["max_marks"],
                passing_marks=data["passing_marks"],
                weightage=data.get("weightage", "100.00"),
                display_order=data.get("display_order", 1),
                is_optional=data.get("is_optional", False),
                include_in_total=data.get("include_in_total", True),
                actor=request.user,
            )
        except ValidationError as error:
            return validation_response(error)
        return api_response(
            {"subject": ReportCardAssessmentSubjectSerializer(assessment_subject).data},
            message="Subject added.",
            status_code=status.HTTP_201_CREATED,
        )


class TeacherReportCardAssessmentSubjectDetailAPI(TeacherReportCardAPIView):
    def get_subject(self, assessment, assessment_subject_id):
        return get_object_or_404(
            ReportCardAssessmentSubject.objects.select_related("assessment", "subject"),
            assessment=assessment,
            pk=assessment_subject_id,
        )

    def patch(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot change this assessment structure.", status_code=status.HTTP_403_FORBIDDEN)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        serializer = ReportCardAssessmentSubjectUpdateSerializer(data=request.data, partial=True)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        data = serializer.validated_data
        fields = dict(data)
        if "subject_id" in fields:
            fields["subject"] = get_object_or_404(Subject, pk=fields.pop("subject_id"), institute=assessment.institute, academic_year=assessment.academic_year)
        try:
            assessment_subject = update_assessment_subject(assessment_subject, actor=request.user, **fields)
        except ValidationError as error:
            return validation_response(error)
        return api_response({"subject": ReportCardAssessmentSubjectSerializer(assessment_subject).data}, message="Subject updated.")

    def delete(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot change this assessment structure.", status_code=status.HTTP_403_FORBIDDEN)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        try:
            remove_assessment_subject(assessment_subject, actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        return api_response(message="Subject deleted.")


class TeacherReportCardMarksGridAPI(TeacherReportCardAPIView):
    def get_subject(self, assessment, assessment_subject_id):
        return get_object_or_404(ReportCardAssessmentSubject, assessment=assessment, pk=assessment_subject_id)

    def get(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        grid = get_marks_grid(assessment_subject)
        return api_response(
            {
                "subject": ReportCardAssessmentSubjectSerializer(assessment_subject).data,
                "rows": ReportCardMarksGridRowSerializer(grid, many=True).data,
            }
        )

    def post(self, request, assessment_id, assessment_subject_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_enter_marks(request.user, assessment):
            return api_response(message="Marks entry is not open.", status_code=status.HTTP_403_FORBIDDEN)
        assessment_subject = self.get_subject(assessment, assessment_subject_id)
        serializer = ReportCardBulkMarksSaveSerializer(data=request.data)
        if not serializer.is_valid():
            return validation_response(serializer.errors)
        try:
            saved = bulk_save_subject_marks(assessment_subject, serializer.validated_data["rows"], actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        return api_response({"saved_count": len(saved)}, message="Marks saved.")


class TeacherReportCardCompletionAPI(TeacherReportCardAPIView):
    def get(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        return api_response({"summary": completion_summary_payload(validate_marks_completion(assessment))})


class TeacherReportCardGenerateAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot generate results.", status_code=status.HTTP_403_FORBIDDEN)
        try:
            results = generate_assessment_results(assessment, actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        return api_response({"generated_count": len(results)}, message="Results generated.")


class TeacherReportCardPublishAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        if not teacher_can_edit_assessment(request.user, assessment):
            return api_response(message="You cannot publish results.", status_code=status.HTTP_403_FORBIDDEN)
        try:
            publish_assessment_results(assessment, actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        return api_response(message="Results published.")


class TeacherReportCardLockAPI(TeacherReportCardAPIView):
    def post(self, request, assessment_id):
        assessment = self.get_assessment(assessment_id)
        try:
            lock_assessment(assessment, actor=request.user)
        except ValidationError as error:
            return validation_response(error)
        return api_response(message="Assessment locked.")


class StudentReportCardAPIView(APIView):
    permission_classes = [IsAuthenticated, IsStudentParentReportCardUser]

    def get_student(self, request):
        return getattr(request.user, "student_profile", None)


class StudentReportCardsAPI(StudentReportCardAPIView):
    def get(self, request):
        student = self.get_student(request)
        if not student:
            return api_response(message="No student profile is linked to this user.", status_code=status.HTTP_404_NOT_FOUND)
        results = get_published_results_for_student(student)
        return list_response(ReportCardStudentResultSerializer(results, many=True).data)


class StudentReportCardDetailAPI(StudentReportCardAPIView):
    def get(self, request, result_id):
        student = self.get_student(request)
        if not student:
            return api_response(message="No student profile is linked to this user.", status_code=status.HTTP_404_NOT_FOUND)
        result = get_object_or_404(get_published_results_for_student(student), pk=result_id)
        if not student_can_view_result(request.user, result):
            return api_response(message="This report card is not available.", status_code=status.HTTP_403_FORBIDDEN)
        subject_rows = get_result_subject_rows(result)
        return api_response(
            {
                "result": ReportCardStudentResultSerializer(result).data,
                "subjects": ReportCardSubjectResultRowSerializer(subject_rows, many=True).data,
            }
        )
