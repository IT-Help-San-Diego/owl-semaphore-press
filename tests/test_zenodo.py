"""Zenodo client + CLI tests against a fake transport (no network)."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from owl_semaphore_press.cli import main as cli_main  # noqa: E402
from owl_semaphore_press.zenodo import ZenodoClient, ZenodoError  # noqa: E402


class FakeTransport:
    """Records requests; replays canned responses keyed by (method, url suffix)."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.routes: dict[tuple[str, str], tuple[int, dict | bytes]] = {}

    def route(self, method: str, suffix: str, status: int, body):
        self.routes[(method, suffix)] = (status, body)

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        for (m, suffix), (status, payload) in self.routes.items():
            if m == method and url.endswith(suffix):
                raw = (payload if isinstance(payload, bytes)
                       else json.dumps(payload).encode())
                return status, raw
        return 404, json.dumps({"message": "not found"}).encode()


DRAFT = {
    "id": 999,
    "state": "unsubmitted",
    "metadata": {"prereserve_doi": {"doi": "10.5281/zenodo.999"},
                 "title": "T", "version": "v1"},
    "links": {"bucket": "https://zenodo.example/api/files/bkt",
              "latest_draft": "https://zenodo.example/api/deposit/depositions/999",
              "html": "https://zenodo.example/deposit/999"},
}


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.t = FakeTransport()
        self.client = ZenodoClient("tok", base_url="https://zenodo.example",
                                   transport=self.t)

    def test_requires_token(self):
        with self.assertRaises(ZenodoError):
            ZenodoClient("", transport=self.t)

    def test_auth_header_sent(self):
        self.t.route("GET", "/api/deposit/depositions/1", 200, {"id": 1})
        self.client.get_deposition(1)
        _, _, headers, _ = self.t.calls[0]
        self.assertEqual(headers["Authorization"], "Bearer tok")

    def test_new_version_follows_latest_draft(self):
        self.t.route("POST", "/actions/newversion", 201,
                     {"links": {"latest_draft":
                                "https://zenodo.example/api/deposit/depositions/999"}})
        self.t.route("GET", "/api/deposit/depositions/999", 200, DRAFT)
        draft = self.client.new_version(20468727)
        self.assertEqual(draft["id"], 999)
        self.assertEqual(ZenodoClient.reserved_doi(draft), "10.5281/zenodo.999")

    def test_upload_puts_into_bucket(self):
        self.t.route("PUT", "/api/files/bkt/data.txt", 201, {"key": "data.txt"})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "data.txt")
            with open(path, "w") as f:
                f.write("hello")
            self.client.upload_file(DRAFT, path)
        method, url, headers, body = self.t.calls[0]
        self.assertEqual((method, body), ("PUT", b"hello"))
        self.assertTrue(url.endswith("/api/files/bkt/data.txt"))

    def test_http_error_raises_with_status(self):
        self.t.route("POST", "/actions/publish", 403, {"message": "forbidden"})
        with self.assertRaises(ZenodoError) as ctx:
            self.client.publish(999)
        self.assertEqual(ctx.exception.status, 403)

    def test_metadata_put_wraps_in_metadata_key(self):
        self.t.route("PUT", "/api/deposit/depositions/999", 200, DRAFT)
        self.client.update_metadata(999, {"title": "X"})
        _, _, _, body = self.t.calls[0]
        self.assertEqual(json.loads(body), {"metadata": {"title": "X"}})


class CliGuardTest(unittest.TestCase):
    def test_publish_refuses_without_yes(self):
        # The guard must fire BEFORE any token/network interaction.
        rc = cli_main(["zenodo", "publish", "999"])
        self.assertEqual(rc, 2)

    def test_missing_token_is_a_clean_error(self):
        env = os.environ.pop("ZENODO_TOKEN", None)
        try:
            with self.assertRaises(SystemExit) as ctx:
                cli_main(["zenodo", "status", "999"])
            self.assertEqual(ctx.exception.code, 2)
        finally:
            if env is not None:
                os.environ["ZENODO_TOKEN"] = env


if __name__ == "__main__":
    unittest.main()
