from django.urls import path

from . import api_views

app_name = "report_card_api"

urlpatterns = [
    path("teacher/assessments/", api_views.TeacherReportCardAssessmentsAPI.as_view(), name="teacher_assessments"),
    path("teacher/assessments/<int:assessment_id>/", api_views.TeacherReportCardAssessmentDetailAPI.as_view(), name="teacher_assessment_detail"),
    path("teacher/assessments/<int:assessment_id>/subjects/", api_views.TeacherReportCardAssessmentSubjectsAPI.as_view(), name="teacher_assessment_subjects"),
    path(
        "teacher/assessments/<int:assessment_id>/subjects/<int:assessment_subject_id>/",
        api_views.TeacherReportCardAssessmentSubjectDetailAPI.as_view(),
        name="teacher_assessment_subject_detail",
    ),
    path(
        "teacher/assessments/<int:assessment_id>/subjects/<int:assessment_subject_id>/marks/",
        api_views.TeacherReportCardMarksGridAPI.as_view(),
        name="teacher_assessment_subject_marks",
    ),
    path("teacher/assessments/<int:assessment_id>/completion/", api_views.TeacherReportCardCompletionAPI.as_view(), name="teacher_assessment_completion"),
    path("teacher/assessments/<int:assessment_id>/generate/", api_views.TeacherReportCardGenerateAPI.as_view(), name="teacher_assessment_generate"),
    path("teacher/assessments/<int:assessment_id>/publish/", api_views.TeacherReportCardPublishAPI.as_view(), name="teacher_assessment_publish"),
    path("teacher/assessments/<int:assessment_id>/lock/", api_views.TeacherReportCardLockAPI.as_view(), name="teacher_assessment_lock"),
    path("student/", api_views.StudentReportCardsAPI.as_view(), name="student_report_cards"),
    path("student/<int:result_id>/", api_views.StudentReportCardDetailAPI.as_view(), name="student_report_card_detail"),
]
