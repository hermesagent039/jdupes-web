import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app import AppState, create_server


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_text("same")
        (self.root / "nested").mkdir()
        (self.root / "nested" / "b.txt").write_text("same")
        self.state = AppState(str(self.root), jdupes_bin="/bin/true")
        self.server = create_server("127.0.0.1", 0, self.state)
        self.server_thread = __import__("threading").Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def request(self, path, method="GET", body=None):
        import urllib.request
        req = urllib.request.Request(self.base + path, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
            body = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(req, body) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_status_starts_idle_and_health(self):
        self.assertEqual(self.request("/healthz")[0], 200)
        status, payload = self.request("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["total_files"], 0)

    def test_start_accepts_search_and_rejects_second_job(self):
        with patch.object(self.state, "start", return_value=True) as start:
            status, payload = self.request("/api/start", "POST", {"mode": "search"})
        self.assertEqual(status, 202)
        self.assertEqual(payload["mode"], "search")
        start.assert_called_once_with("search", False)

    def test_delete_requires_confirmation(self):
        status, payload = self.request("/api/start", "POST", {"mode": "delete"})
        self.assertEqual(status, 400)
        self.assertIn("confirmation", payload["error"])

    def test_path_is_recursive_root(self):
        self.assertEqual(self.state.root, os.path.realpath(self.root))


if __name__ == "__main__":
    unittest.main()
