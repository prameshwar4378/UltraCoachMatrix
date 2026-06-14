from django.test import TestCase
from django.urls import reverse


class AndroidAppDownloadTests(TestCase):
    def test_apk_download_is_public_and_has_attachment_headers(self):
        response = self.client.get(reverse("apk_download"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.android.package-archive",
        )
        self.assertIn("UltraCoachMatrix.apk", response["Content-Disposition"])
        response.close()

    def test_homepage_uses_direct_apk_download_url(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, reverse("apk_download"), count=2)
