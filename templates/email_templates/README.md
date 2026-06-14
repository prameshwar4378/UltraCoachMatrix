# UltraCoachMatrix email templates

The software sends only these transactional emails:

| Action | Template |
| --- | --- |
| Student welcome with credentials and app link | `student_welcome_credentials.html` |
| Teacher welcome with credentials and login link | `teacher_welcome_credentials.html` |
| Institute welcome with credentials and login link | `institute_welcome_credentials.html` |
| Payment received or corrected | `payment_confirmation_receipt.html` |

All templates extend `base_email.html`. Email work is registered with
`transaction.on_commit()` and normally runs in a background thread.

Configure SMTP with the `EMAIL_*` environment variables. The bundled APK is
served from `/download/ultra-coach-matrix.apk` and used in student welcome
emails and website download buttons. `STUDENT_APP_DOWNLOAD_URL` can override
that public link, and `STUDENT_APP_APK_PATH` can override the local APK path.
