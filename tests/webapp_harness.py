"""Helpers for tests that talk to the web backend over real HTTP.

    from tests.webapp_harness import WebAppTestCase

    class MyFeatureTests(WebAppTestCase):
        def test_x(self):
            self.call("POST", "/api/new", {"name": "T"})

Each test class gets its own server on a free port and a fresh session.
"""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from typing import Any

from webapp import core
from webapp import server as web


class _QuietHandler(web.Handler):
    def log_message(self, fmt, *args):  # keep test output readable
        pass


class WebAppTestCase(unittest.TestCase):
    httpd = None
    base = ""

    @classmethod
    def setUpClass(cls):
        core.reset_session()
        cls.httpd = web.ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def call(self, method: str, path: str, body: Any = None, *, expect: int = 200) -> Any:
        """Send a request; assert the status code and return the decoded JSON."""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"} if data else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, raw = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        self.assertEqual(status, expect, raw.decode("utf-8", "replace")[:500])
        text = raw.decode("utf-8")
        return json.loads(text) if text and text.lstrip()[:1] in "[{" else text

    def get_text(self, path: str) -> str:
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.read().decode("utf-8")
