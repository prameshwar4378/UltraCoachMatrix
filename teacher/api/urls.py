from django.urls import path

from . import views


app_name = "teacher_mobile_api"

urlpatterns = [
    path("dashboard/", views.TeacherDashboardAPI.as_view(), name="dashboard"),
    path("academic-years/", views.TeacherAcademicYearsAPI.as_view(), name="academic_years"),
    path("classes/", views.TeacherClassesAPI.as_view(), name="classes"),
    path("classes/<int:batch_id>/students/", views.TeacherClassStudentsAPI.as_view(), name="class_students"),
    path("classes/<int:batch_id>/students/<int:session_id>/", views.TeacherClassStudentDetailAPI.as_view(), name="class_student_detail"),
    path("attendance/", views.TeacherAttendanceAPI.as_view(), name="attendance"),
    path("assignments/", views.TeacherAssignmentsAPI.as_view(), name="assignments"),
    path("assignments/<int:assignment_id>/", views.TeacherAssignmentDetailAPI.as_view(), name="assignment_detail"),
    path("notices/", views.TeacherNoticesAPI.as_view(), name="notices"),
    path("notices/<int:notice_id>/read/", views.TeacherNoticeReadAPI.as_view(), name="notice_read"),
    path("messages/", views.TeacherMessagesAPI.as_view(), name="messages"),
    path("exams/", views.TeacherExamsAPI.as_view(), name="exams"),
    path("exams/<int:exam_id>/", views.TeacherExamDetailAPI.as_view(), name="exam_detail"),
    path("exams/<int:exam_id>/publish/", views.TeacherExamPublishAPI.as_view(), name="exam_publish"),
    path("questions/", views.TeacherQuestionsAPI.as_view(), name="questions"),
    path("questions/<int:question_id>/", views.TeacherQuestionDetailAPI.as_view(), name="question_detail"),
    path("submissions/", views.TeacherSubmissionsAPI.as_view(), name="submissions"),
    path("submissions/<int:attempt_id>/force-submit/", views.TeacherSubmissionForceSubmitAPI.as_view(), name="submission_force_submit"),
    path("submissions/<int:attempt_id>/reset/", views.TeacherSubmissionResetAPI.as_view(), name="submission_reset"),
    path("results/", views.TeacherResultsAPI.as_view(), name="results"),
    path("results/<int:exam_id>/publish/", views.TeacherResultPublishAPI.as_view(), name="result_publish"),
    path("results/<int:exam_id>/hide/", views.TeacherResultHideAPI.as_view(), name="result_hide"),
    path("reports/attendance/", views.TeacherAttendanceReportAPI.as_view(), name="attendance_report"),
    path("reports/results/", views.TeacherResultReportAPI.as_view(), name="result_report"),
]
