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
