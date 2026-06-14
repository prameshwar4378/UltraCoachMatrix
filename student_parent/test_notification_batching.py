from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from institute_admin.models import Notice
from super_admin.models import Institute

from .models import PushNotification, StudentProfile, UserDevice
from .notifications import FIREBASE_MULTICAST_LIMIT, notify_notice_published


class FakeMessaging:
    def __init__(self, failed_tokens=None):
        self.failed_tokens = failed_tokens or {}
        self.multicast_sizes = []

    @staticmethod
    def Notification(**kwargs):
        return kwargs

    @staticmethod
    def AndroidConfig(**kwargs):
        return kwargs

    @staticmethod
    def AndroidNotification(**kwargs):
        return kwargs

    @staticmethod
    def Aps(**kwargs):
        return kwargs

    @staticmethod
    def APNSPayload(**kwargs):
        return kwargs

    @staticmethod
    def APNSConfig(**kwargs):
        return kwargs

    @staticmethod
    def MulticastMessage(**kwargs):
        return SimpleNamespace(**kwargs)

    def send_each_for_multicast(self, message):
        self.multicast_sizes.append(len(message.tokens))
        responses = []
        for token in message.tokens:
            error = self.failed_tokens.get(token)
            responses.append(
                SimpleNamespace(
                    success=error is None,
                    message_id="" if error else f"message-{token}",
                    exception=Exception(error) if error else None,
                )
            )
        return SimpleNamespace(responses=responses)


class NoticeNotificationBatchingTests(TestCase):
    def setUp(self):
        self.institute = Institute.objects.create(
            name="Batch Notification Institute",
            code="batch-notification",
        )
        self.user_with_devices = User.objects.create_user(username="student-devices")
        self.user_without_devices = User.objects.create_user(username="student-no-device")
        self.student_with_devices = StudentProfile.objects.create(
            institute=self.institute,
            user=self.user_with_devices,
            admission_number="BATCH-001",
        )
        self.student_without_devices = StudentProfile.objects.create(
            institute=self.institute,
            user=self.user_without_devices,
            admission_number="BATCH-002",
        )
        self.notice = Notice.objects.create(
            institute=self.institute,
            title="Institute notice",
            message="This should be delivered in multicast batches.",
            push_to_app=True,
            is_published=True,
        )

    def test_notice_devices_are_sent_in_firebase_batches(self):
        devices = [
            UserDevice(
                user=self.user_with_devices,
                token=f"token-{index}",
                platform=UserDevice.Platform.ANDROID,
            )
            for index in range(FIREBASE_MULTICAST_LIMIT + 1)
        ]
        UserDevice.objects.bulk_create(devices, batch_size=500)
        failed_token = "token-17"
        messaging = FakeMessaging(
            {
                failed_token: "registration-token-not-registered",
            }
        )

        with patch(
            "student_parent.notifications._firebase_messaging",
            return_value=(messaging, ""),
        ):
            records = notify_notice_published(self.notice)

        self.assertEqual(messaging.multicast_sizes, [500, 1])
        self.assertEqual(len(records), 2)
        delivered = PushNotification.objects.get(user=self.user_with_devices)
        skipped = PushNotification.objects.get(user=self.user_without_devices)
        self.assertEqual(delivered.status, PushNotification.Status.SENT)
        self.assertIn("registration-token-not-registered", delivered.error_message)
        self.assertEqual(
            delivered.data["student_id"],
            str(self.student_with_devices.pk),
        )
        self.assertEqual(skipped.status, PushNotification.Status.SKIPPED)
        self.assertFalse(UserDevice.objects.get(token=failed_token).is_active)

    def test_failed_multicast_marks_user_notification_failed(self):
        UserDevice.objects.create(
            user=self.user_with_devices,
            token="failed-token",
            platform=UserDevice.Platform.ANDROID,
        )
        messaging = FakeMessaging({"failed-token": "temporary Firebase failure"})

        with patch(
            "student_parent.notifications._firebase_messaging",
            return_value=(messaging, ""),
        ):
            notify_notice_published(self.notice)

        record = PushNotification.objects.get(user=self.user_with_devices)
        self.assertEqual(record.status, PushNotification.Status.FAILED)
        self.assertIn("temporary Firebase failure", record.error_message)

    def test_missing_firebase_configuration_skips_devices_without_network_calls(self):
        UserDevice.objects.create(
            user=self.user_with_devices,
            token="configured-later",
            platform=UserDevice.Platform.ANDROID,
        )

        with patch(
            "student_parent.notifications._firebase_messaging",
            return_value=(None, "Firebase credentials are unavailable."),
        ):
            notify_notice_published(self.notice)

        record = PushNotification.objects.get(user=self.user_with_devices)
        self.assertEqual(record.status, PushNotification.Status.SKIPPED)
        self.assertEqual(
            record.error_message,
            "Firebase credentials are unavailable.",
        )
