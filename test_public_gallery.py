import asyncio
import unittest
from unittest.mock import patch

from fastapi import Request
from fastapi.responses import Response
import app


class PublicGalleryAccessTests(unittest.TestCase):
    def request(self, path, method):
        scope = {"type": "http", "path": path, "method": method,
                 "scheme": "http", "server": ("test", 80), "headers": [], "query_string": b""}
        async def downstream(request):
            return Response(status_code=204)
        with patch.object(app, "PUBLIC_GALLERY_ONLY", True):
            return asyncio.run(app.protect_public_gallery(Request(scope), downstream))

    def test_private_pages_and_records_are_blocked(self):
        for path in ['/image-studio', '/prompts', '/connections', '/api/inquiries',
                     '/api/backup', '/uploads/original.png', '/openapi.json', '/docs']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path, 'GET').status_code, 404)

    def test_visitors_cannot_edit_gallery_settings(self):
        self.assertEqual(self.request('/api/gallery-settings', 'PUT').status_code, 404)
        self.assertEqual(self.request('/api/inquiries', 'POST').status_code, 404)

    def test_gallery_and_preview_reads_are_allowed(self):
        for path in ['/gallery', '/inquire', '/api/gallery-settings', '/api/gallery-artworks',
                     '/api/gallery-artworks/1/image', '/static/gallery.js', '/api/health']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path, 'GET').status_code, 204)

    def test_release_requires_endpoint_authorization(self):
        self.assertEqual(self.request('/api/gallery-release-package', 'GET').status_code, 404)
        self.assertEqual(self.request('/api/gallery-release-package', 'POST').status_code, 204)
