import json
from pathlib import Path

from django.conf import settings
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
        parser.add_argument(
            "--user-status",
            metavar="USERNAME",
            help="Show registered devices and latest push result for this user.",
        )
        parser.add_argument("--title", default="UltraCoachMatrix test notification")
        parser.add_argument("--body", default="Firebase push notification setup is working.")

    def handle(self, *args, **options):
        status = firebase_configuration_status()
        android_status = self._android_firebase_status()
        self.stdout.write(f"Enabled: {status.get('enabled', False)}")
        self.stdout.write(f"Ready: {status.get('ready', False)}")
        if status.get("credentials_file"):
            self.stdout.write(f"Credentials: {status['credentials_file']}")
        if status.get("project_id"):
            self.stdout.write(f"Project ID: {status['project_id']}")
        if android_status.get("project_id"):
            self.stdout.write(f"Android google-services project ID: {android_status['project_id']}")
        if android_status.get("project_number"):
            self.stdout.write(
                f"Android google-services project number: {android_status['project_number']}"
            )
        if android_status.get("storage_bucket"):
            self.stdout.write(
                f"Android google-services storage bucket: {android_status['storage_bucket']}"
            )
        if android_status.get("detail"):
            self.stdout.write(f"Android config: {android_status['detail']}")
        if android_status.get("warning"):
            self.stdout.write(self.style.WARNING(android_status["warning"]))
        if (
            status.get("project_id")
            and android_status.get("project_id")
            and status["project_id"] != android_status["project_id"]
        ):
            self.stdout.write(
                self.style.WARNING(
                    "Firebase project mismatch: backend credentials and Android "
                    "google-services.json must belong to the same Firebase project."
                )
            )
        self.stdout.write(f"Status: {status['detail']}")

        status_username = options.get("user_status")
        if status_username:
            self._write_user_status(status_username)

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
        self._write_user_status(username)

    def _write_user_status(self, username):
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"User '{username}' does not exist.") from exc

        devices = list(UserDevice.objects.filter(user=user).order_by("-last_seen_at")[:10])
        active_devices = sum(1 for device in devices if device.is_active)
        total_devices = UserDevice.objects.filter(user=user).count()
        self.stdout.write(f"User: {user.username}")
        self.stdout.write(f"Devices: {active_devices} active of {total_devices} total")
        for device in devices:
            token_tail = device.token[-12:] if device.token else ""
            self.stdout.write(
                "  "
                f"#{device.pk} {device.platform} "
                f"active={device.is_active} "
                f"last_seen={device.last_seen_at.isoformat()} "
                f"token_tail=...{token_tail}"
            )

        latest = PushNotification.objects.filter(user=user).first()
        if not latest:
            self.stdout.write("Latest notification: none")
            return
        self.stdout.write(
            "Latest notification: "
            f"#{latest.pk} {latest.notification_type} {latest.status} "
            f"created={latest.created_at.isoformat()} "
            f"sent={latest.sent_at.isoformat() if latest.sent_at else '-'}"
        )
        if latest.firebase_message_id:
            self.stdout.write(f"Latest Firebase message ID: {latest.firebase_message_id}")
        if latest.error_message:
            self.stdout.write(f"Latest error: {latest.error_message}")

    def _android_firebase_status(self):
        workspace_root = Path(settings.BASE_DIR).parents[1]
        google_services_path = (
            workspace_root
            / "FrontEnd"
            / "ultracoachmatrix"
            / "android"
            / "app"
            / "google-services.json"
        )
        if not google_services_path.exists():
            return {}
        try:
            with google_services_path.open(encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            return {"detail": f"Could not read {google_services_path}: {exc}"}

        project_info = data.get("project_info") or {}
        project_id = project_info.get("project_id") or ""
        project_number = project_info.get("project_number") or ""
        storage_bucket = project_info.get("storage_bucket") or ""
        package_name = ""
        clients = data.get("client") or []
        if clients:
            package_name = (
                (clients[0].get("client_info") or {})
                .get("android_client_info", {})
                .get("package_name", "")
            )
        detail = f"{google_services_path}"
        if package_name:
            detail = f"{detail} package={package_name}"
        warning = ""
        if project_id and storage_bucket and project_id not in storage_bucket:
            warning = (
                "Android google-services.json looks inconsistent: storage_bucket "
                "does not contain the same project_id. Download a fresh Android "
                "google-services.json from Firebase instead of editing it by hand."
            )
        return {
            "project_id": project_id,
            "project_number": project_number,
            "storage_bucket": storage_bucket,
            "detail": detail,
            "warning": warning,
        }
