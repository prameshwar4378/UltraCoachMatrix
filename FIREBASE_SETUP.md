# Firebase Server Credentials

The Firebase service-account JSON is a server secret. Do not place it inside
this repository, the Flutter application, an APK, static files, or media files.

## Setup

1. Store the downloaded JSON in a protected directory outside the project.
2. Restrict filesystem access to the account that runs Django and Celery.
3. Set one of these environment variables to its absolute path:

   ```powershell
   $env:FIREBASE_CREDENTIALS_FILE="C:\secure\ultracoachmatrix\firebase-service-account.json"
   ```

   or:

   ```powershell
   $env:GOOGLE_APPLICATION_CREDENTIALS="C:\secure\ultracoachmatrix\firebase-service-account.json"
   ```

4. Start Django and Celery from the same environment so both processes can
   access the credential.

When no credential path is configured, the application continues to run and
records push notifications as skipped with a configuration message.

## Current Production Project

The current production Firebase project is:

```text
push-notification-ucm-producti
```

The backend service-account JSON, Android `google-services.json`, and any
Flutter web Firebase build values must all come from this same Firebase project.
Do not mix it with the older `pushnotification-3839e` project, or Firebase may
accept device registration but reject sends with sender/project permission
errors.

For production, keep these values in the Django `.env` file next to
`manage.py`, or in the service manager environment:

```env
FIREBASE_CREDENTIALS_FILE=/home/ultracoachmatrix/.secrets/firebase-service-account.json
FIREBASE_PROJECT_ID=push-notification-ucm-producti
PUSH_NOTIFICATIONS_ENABLED=true
BACKGROUND_JOB_SYNC_FEE_FALLBACK=true
BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=true
```

The service account also needs the Google Cloud IAM role:

```text
Firebase Cloud Messaging API Admin
```

Make sure the Firebase Cloud Messaging API is enabled for the same project.

## Android App Configuration

If the Firebase project changes, the Android app must also be rebuilt with the
matching Firebase Android config:

1. In Firebase Console, open `push-notification-ucm-producti`.
2. Add/open the Android app with package name:

   ```text
   ultracoachmatrix.in
   ```

3. Download the Android `google-services.json`.
4. Replace:

   ```text
   FrontEnd/ultracoachmatrix/android/app/google-services.json
   ```

5. Rebuild and reinstall the APK.
6. Log in again on the mobile app so the device registers a new FCM token for
   the new Firebase project.

Old device tokens from another Firebase project cannot be used for the new
project.

## Rotation

If the old JSON was emailed, uploaded, backed up to a shared location, or
otherwise exposed:

1. Create a replacement key in Google Cloud IAM for the Firebase service
   account.
2. Deploy the replacement credential through the environment variable.
3. Verify push delivery.
4. Disable and delete the old key in Google Cloud IAM.

Removing the local JSON file does not revoke the key. Revocation must happen in
Google Cloud.

## Production Linux / VPS

Uploading the JSON file is not enough. The web application must receive its
absolute path when the Django process starts.

1. Store the replacement credential outside the repository, for example:

   ```text
   /home/ultracoachmatrix/.secrets/firebase-service-account.json
   ```

2. Add these values to the production `.env`, systemd service, or process
   manager environment:

   ```env
   FIREBASE_CREDENTIALS_FILE=/home/ultracoachmatrix/.secrets/firebase-service-account.json
   BACKGROUND_JOB_SYNC_FEE_FALLBACK=true
   BACKGROUND_JOB_SYNC_NOTICE_FALLBACK=true
   ```

3. Restart the Django/Gunicorn service.
4. Open a Bash console in the deployed project directory and verify:

   ```bash
   python manage.py check_push_notifications
   python manage.py check_push_notifications --user-status STUDENT_USERNAME
   python manage.py check_push_notifications --send-test STUDENT_USERNAME
   ```

The first command must report `Ready: True`. The user status command must show
at least one active device for the logged-in mobile user. The send-test command
must report `Notification status: SENT`.

When the frontend source is present on the same machine, the check command also
prints the Android `google-services.json` project ID and warns if it does not
match the backend service-account project.

If the user status command shows no active devices, log out and log in again on
the mobile app, allow notifications, then run the status command again. If it
shows active devices but the send test is skipped or failed, check the printed
latest error. A `sender id` or `requested entity was not found` error usually
means the server service-account JSON does not belong to the same Firebase
project as the Android app's `google-services.json`.

If production does not run Celery/Redis, keep these enabled in the WSGI or
process environment so fee and notice notification jobs can run synchronously:

```python
os.environ["BACKGROUND_JOB_SYNC_FEE_FALLBACK"] = "true"
os.environ["BACKGROUND_JOB_SYNC_NOTICE_FALLBACK"] = "true"
```

## Flutter Web / PWA on ultracoachmatrix.in

Web push also needs a Firebase Web app config and VAPID key. Android
`google-services.json` is not enough for browser notifications.

1. In Firebase Console, add `ultracoachmatrix.in` and
   `www.ultracoachmatrix.in` under Authentication > Settings >
   Authorized domains.
2. In Project settings, create or open the Web app and copy its config.
3. Build Flutter web with the public web config:

   ```bash
   flutter build web --release \
     --dart-define=API_BASE_URL=https://ultracoachmatrix.in \
     --dart-define=FIREBASE_WEB_API_KEY=<web-api-key> \
     --dart-define=FIREBASE_WEB_APP_ID=<web-app-id> \
     --dart-define=FIREBASE_WEB_MESSAGING_SENDER_ID=<web-messaging-sender-id> \
     --dart-define=FIREBASE_WEB_PROJECT_ID=push-notification-ucm-producti \
     --dart-define=FIREBASE_WEB_AUTH_DOMAIN=push-notification-ucm-producti.firebaseapp.com \
     --dart-define=FIREBASE_WEB_STORAGE_BUCKET=<web-storage-bucket> \
     --dart-define=FIREBASE_WEB_VAPID_KEY=<web-push-certificate-key>
   ```

4. Before uploading the web build, set the same public values in
   `web/firebase-config.js` or replace that file in the generated build output.
   The deployed site must serve this file and `/firebase-messaging-sw.js` from
   the domain root.
5. Open the deployed site over `https://ultracoachmatrix.in`, log in as a
   student, allow notifications, and check `/api/mobile/push/status/` from the
   app session. It should show at least one active `WEB` device.
