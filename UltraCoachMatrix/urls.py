"""
URL configuration for UltraCoachMatrix project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from django.views.generic import RedirectView
from student_parent import views as student_parent_views
from super_admin import views as super_admin_views
from super_admin import urls as super_admin_urls
from Website import urls as website_urls
urlpatterns = [
    path('api/mobile/attendance/', student_parent_views.mobile_attendance, name='mobile_attendance'),
    path('api/mobile/homework/', student_parent_views.mobile_homework_planner, name='mobile_homework_planner'),
    path('api/mobile/notices/', student_parent_views.mobile_notices, name='mobile_notices'),
    path('api/mobile/notices/<int:notice_id>/read/', student_parent_views.mobile_notice_mark_read, name='mobile_notice_mark_read'),
    path('api/mobile/devices/register/', student_parent_views.mobile_register_device, name='mobile_register_device'),
    path('api/mobile/devices/unregister/', student_parent_views.mobile_unregister_device, name='mobile_unregister_device'),
    path('api/mobile/notifications/', student_parent_views.mobile_notifications, name='mobile_notifications'),
    path(
        'api/mobile/homework/document/download/',
        student_parent_views.mobile_homework_document_download,
        name='mobile_homework_document_download',
    ),
    path('dashboard/', super_admin_views.role_home, name='school_dashboard'),
    path(
        'institute/profile/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='institute_profile',
    ),
    path(
        'institute/billing/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='subscription_billing',
    ),
    path(
        'institute/security/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='security_settings',
    ),
    path(
        'institute/tasks/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='proxy_adjustment_panel',
    ),
    path(
        'institute/planner/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='timetable_builder',
    ),
    path(
        'institute/setup/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='timetable_list',
    ),
    path(
        'institute/planner/alternate/',
        RedirectView.as_view(pattern_name='institute_admin:dashboard', permanent=False),
        name='timetable_builder_template_2',
    ),
    path('institute/', include('institute_admin.urls')),
    path('teacher/', include('teacher.urls')),
    path('student/', include('student_parent.urls')),
    path('', include('accountant.urls')),
    path('', include(super_admin_urls)),
    path('', include(website_urls)),
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
