"""Zenodo client + CLI tests against a fake transport (no network)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib.parse import unquote

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from owl_semaphore_press import zenodo as zenodo_mod  # noqa: E402
from owl_semaphore_press.cli import main as cli_main  # noqa: E402
from owl_semaphore_press.zenodo import (  # noqa: E402
    UPLOAD_RETRIES,
    ZenodoClient,
    ZenodoError,
)


class FakeTransport:
    """Records requests; replays canned responses keyed by (method, url suffix).

    Streaming bodies are drained to bytes before recording so assertions see
    content; ``streamed`` remembers which calls carried a file-like body.
    Exceptions in ``fail_queue`` are raised one per call (after recording it)
    to simulate connection-level failures.
    """

    def __init__(self):
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.streamed: list[bool] = []
        self.routes: dict[tuple[str, str], tuple[int, dict | bytes]] = {}
        self.fail_queue: list[Exception] = []

    def route(self, method: str, suffix: str, status: int, body):
        self.routes[(method, suffix)] = (status, body)

    def __call__(self, method, url, headers, body):
        self.streamed.append(hasattr(body, "read"))
        if hasattr(body, "read"):
            body = body.read()
        self.calls.append((method, url, headers, body))
        if self.fail_queue:
            raise self.fail_queue.pop(0)
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


def _write(dirname: str, name: str, data: bytes) -> str:
    path = os.path.join(dirname, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.t = FakeTransport()
        self.sleeps: list[float] = []
        self.client = ZenodoClient("tok", base_url="https://zenodo.example",
                                   transport=self.t, sleep=self.sleeps.append)

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
            self.client.upload_file(DRAFT, _write(d, "data.txt", b"hello"))
        method, url, headers, body = self.t.calls[0]
        self.assertEqual((method, body), ("PUT", b"hello"))
        self.assertTrue(url.endswith("/api/files/bkt/data.txt"))

    def test_upload_streams_from_disk_with_content_length(self):
        # The body must reach the transport as an open file (streamed by
        # http.client in blocks), with an explicit Content-Length so urllib
        # does not fall back to chunked Transfer-Encoding.
        self.t.route("PUT", "/api/files/bkt/data.bin", 201, {"key": "data.bin"})
        with tempfile.TemporaryDirectory() as d:
            self.client.upload_file(DRAFT, _write(d, "data.bin", b"x" * 1000))
        self.assertEqual(self.t.streamed, [True])
        _, _, headers, body = self.t.calls[0]
        self.assertEqual(headers["Content-Length"], "1000")
        self.assertEqual(body, b"x" * 1000)

    def test_upload_retries_after_broken_pipe(self):
        # Regression: the owl-semaphore v3.0.1 release lost a 77 MB upload to
        # a single BrokenPipeError with no retry.
        self.t.route("PUT", "/api/files/bkt/data.txt", 201, {"key": "data.txt"})
        self.t.fail_queue = [BrokenPipeError(32, "Broken pipe")]
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "data.txt", b"hello")
            with contextlib.redirect_stderr(io.StringIO()) as err:
                result = self.client.upload_file(DRAFT, path)
        self.assertEqual(result, {"key": "data.txt"})
        self.assertEqual(len(self.t.calls), 2)
        self.assertEqual(self.sleeps, [2.0])
        self.assertIn("retry 1/", err.getvalue())

    def test_upload_resends_full_body_after_midstream_failure(self):
        # First attempt: the peer reads 3 bytes then the pipe breaks. The
        # retry must re-open the file so the full content is sent again.
        received: list[bytes] = []

        def transport(method, url, headers, body):
            if not received:
                received.append(body.read(3))
                raise BrokenPipeError(32, "Broken pipe")
            received.append(body.read())
            return 201, json.dumps({"key": "data.txt"}).encode()

        client = ZenodoClient("tok", base_url="https://zenodo.example",
                              transport=transport, sleep=lambda s: None)
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "data.txt", b"0123456789")
            with contextlib.redirect_stderr(io.StringIO()):
                client.upload_file(DRAFT, path)
        self.assertEqual(received, [b"012", b"0123456789"])

    def test_upload_backoff_doubles_per_retry(self):
        self.t.route("PUT", "/api/files/bkt/data.txt", 201, {"key": "data.txt"})
        self.t.fail_queue = [ConnectionResetError(54, "reset"),
                             TimeoutError("timed out"),
                             BrokenPipeError(32, "Broken pipe")]
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "data.txt", b"hello")
            with contextlib.redirect_stderr(io.StringIO()):
                self.client.upload_file(DRAFT, path)
        self.assertEqual(len(self.t.calls), 4)
        self.assertEqual(self.sleeps, [2.0, 4.0, 8.0])

    def test_upload_gives_up_after_bounded_retries(self):
        self.t.fail_queue = [BrokenPipeError(32, "Broken pipe")
                             for _ in range(1 + UPLOAD_RETRIES)]
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "data.txt", b"hello")
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(ZenodoError) as ctx:
                    self.client.upload_file(DRAFT, path)
        self.assertEqual(len(self.t.calls), 1 + UPLOAD_RETRIES)
        self.assertIsInstance(ctx.exception.__cause__, BrokenPipeError)
        self.assertIn("failed after", str(ctx.exception))

    def test_upload_does_not_retry_http_errors(self):
        # A 4xx/5xx is a server verdict on a request it fully received;
        # retrying wouldn't help and could mask a real problem.
        self.t.route("PUT", "/api/files/bkt/data.txt", 403,
                     {"message": "forbidden"})
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "data.txt", b"hello")
            with self.assertRaises(ZenodoError) as ctx:
                self.client.upload_file(DRAFT, path)
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(len(self.t.calls), 1)
        self.assertEqual(self.sleeps, [])

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

    def test_upload_percent_encodes_filename(self):
        # Spaces/'#' must be encoded or urllib crashes / silently truncates the key.
        self.t.route("PUT", "/api/files/bkt/a%20b%23c.pdf", 201, {"key": "a b#c.pdf"})
        with tempfile.TemporaryDirectory() as d:
            self.client.upload_file(DRAFT, _write(d, "a b#c.pdf", b"x"))
        _, url, _, _ = self.t.calls[0]
        self.assertTrue(url.endswith("/api/files/bkt/a%20b%23c.pdf"), url)

    def test_delete_and_clear_files(self):
        self.t.route("GET", "/api/deposit/depositions/999/files", 200,
                     [{"id": "f1", "filename": "old-v1.zip"},
                      {"id": "f2", "filename": "old-v1.pdf"}])
        self.t.route("DELETE", "/api/deposit/depositions/999/files/f1", 204, b"")
        self.t.route("DELETE", "/api/deposit/depositions/999/files/f2", 204, b"")
        deleted = self.client.clear_files(999)
        self.assertEqual(deleted, ["old-v1.zip", "old-v1.pdf"])
        deletes = [(m, u) for m, u, _, _ in self.t.calls if m == "DELETE"]
        self.assertEqual(len(deletes), 2)

    def test_clear_files_on_empty_draft_is_noop(self):
        # --fresh runs clear_files before uploading; after a failed upload a
        # rerun sees an already-emptied draft and must be a safe no-op.
        self.t.route("GET", "/api/deposit/depositions/999/files", 200, [])
        self.assertEqual(self.client.clear_files(999), [])
        self.assertEqual([m for m, _, _, _ in self.t.calls], ["GET"])


class FakeBucket:
    """Stateful transport mimicking a draft deposition + its files bucket.

    ``put_plan`` scripts each PUT in order: "fail" raises BrokenPipeError
    (after draining the body, like a peer that hung up), "ok" stores the file.
    An exhausted plan defaults to "ok".
    """

    def __init__(self, files: dict[str, str] | None = None):
        self.files = dict(files or {})  # id -> filename
        self.deletes: list[str] = []
        self.put_plan: list[str] = []
        self.puts = 0

    def __call__(self, method, url, headers, body):
        if hasattr(body, "read"):
            body = body.read()
        if method == "GET" and url.endswith("/api/deposit/depositions/999"):
            dep = dict(DRAFT)
            return 200, json.dumps(dep).encode()
        if method == "GET" and url.endswith("/api/deposit/depositions/999/files"):
            listing = [{"id": fid, "filename": name}
                       for fid, name in sorted(self.files.items())]
            return 200, json.dumps(listing).encode()
        if method == "DELETE" and "/files/" in url:
            self.deletes.append(self.files.pop(url.rsplit("/", 1)[1]))
            return 204, b""
        if method == "PUT" and "/api/files/bkt/" in url:
            self.puts += 1
            if self.put_plan and self.put_plan.pop(0) == "fail":
                raise BrokenPipeError(32, "Broken pipe")
            name = unquote(url.rsplit("/", 1)[1])
            self.files[f"id-{name}"] = name
            return 201, json.dumps({"key": name}).encode()
        return 404, json.dumps({"message": "not found"}).encode()


class CliUploadFreshTest(unittest.TestCase):
    """End-to-end `owl-press zenodo upload --fresh` against a fake bucket."""

    def _run(self, bucket: FakeBucket, argv: list[str]) -> int:
        with mock.patch.object(zenodo_mod, "_urllib_transport", bucket), \
             mock.patch.object(zenodo_mod, "time", mock.Mock(sleep=lambda s: None)), \
             mock.patch.dict(os.environ, {"ZENODO_TOKEN": "tok"}), \
             contextlib.redirect_stdout(io.StringIO()), \
             contextlib.redirect_stderr(io.StringIO()):
            return cli_main(argv)

    def test_fresh_upload_survives_transient_failure(self):
        bucket = FakeBucket({"f1": "owl-semaphore-v3.0.0.zip"})
        bucket.put_plan = ["fail", "ok"]
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "owl-semaphore-v3.0.1.zip", b"release bytes")
            rc = self._run(bucket, ["zenodo", "upload", "999", path, "--fresh"])
        self.assertEqual(rc, 0)
        self.assertEqual(bucket.deletes, ["owl-semaphore-v3.0.0.zip"])
        self.assertEqual(sorted(bucket.files.values()),
                         ["owl-semaphore-v3.0.1.zip"])
        self.assertEqual(bucket.puts, 2)

    def test_fresh_rerun_after_total_failure_is_safe(self):
        # The --fresh deletion of inherited files runs BEFORE the upload; if
        # the upload then dies for good, rerunning `upload --fresh` must not
        # error on the already-emptied draft and must leave exactly the new
        # release set.
        bucket = FakeBucket({"f1": "owl-semaphore-v3.0.0.zip"})
        bucket.put_plan = ["fail"] * (1 + UPLOAD_RETRIES)
        with tempfile.TemporaryDirectory() as d:
            path = _write(d, "owl-semaphore-v3.0.1.zip", b"release bytes")
            rc1 = self._run(bucket, ["zenodo", "upload", "999", path, "--fresh"])
            rc2 = self._run(bucket, ["zenodo", "upload", "999", path, "--fresh"])
        self.assertEqual(rc1, 1)   # clean ZenodoError exit, not a traceback
        self.assertEqual(rc2, 0)
        # Inherited file deleted exactly once (first run); the rerun's
        # clear_files saw an empty draft and deleted nothing extra.
        self.assertEqual(bucket.deletes, ["owl-semaphore-v3.0.0.zip"])
        self.assertEqual(sorted(bucket.files.values()),
                         ["owl-semaphore-v3.0.1.zip"])


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
