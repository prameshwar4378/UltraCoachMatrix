from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from student_parent.models import PushNotification, UserDevice
from student_parent.notifications import firebase_configuration_status, send_push_to_user


class Command(BaseCommand):
    help = "Check Firebase push notification backend configuration."

    def add_arguments(self, parser):
        parser.add_argument(
            "--send-test",
            metavar="USERNAME",
            help="Send a test push notification to the active devices of this user.",
        )
        parser.add_argument("--title", default="UltraCoachMatrix test notification")
        parser.add_argument("--body", default="Firebase push notification setup is working.")

    def handle(self, *args, **options):
        status = firebase_configuration_status()
        self.stdout.write(f"Enabled: {status.get('enabled', False)}")
        self.stdout.write(f"Ready: {status.get('ready', False)}")
        if status.get("credentials_file"):
            self.stdout.write(f"Credentials: {status['credentials_file']}")
        if status.get("project_id"):
            self.stdout.write(f"Project ID: {status['project_id']}")
        self.stdout.write(f"Status: {status['detail']}")

        username = options.get("send_test")
        if not username:
            return
        if not status.get("ready"):
            raise CommandError("Cannot send test push until Firebase is ready.")

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{username}' does not exist.") from exc

        active_devices = UserDevice.objects.filter(user=user, is_active=True).count()
        if not active_devices:
            raise CommandError(f"User '{username}' has no active registered devices.")

        notification = send_push_to_user(
            user,
            PushNotification.NotificationType.CUSTOM,
            options["title"],
            options["body"],
            {"type": PushNotification.NotificationType.CUSTOM, "source": "management_command"},
        )
        self.stdout.write(f"Notification status: {notification.status}")
        if notification.firebase_message_id:
            self.stdout.write(f"Firebase message ID: {notification.firebase_message_id}")
        if notification.error_message:
            self.stdout.write(f"Error: {notification.error_message}")
