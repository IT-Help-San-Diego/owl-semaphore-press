"""Zenodo release automation: reserve draft → read DOI → upload → publish.

Implements the owl-semaphore release convention (RELEASE-PROCESS.md): the
version-specific DOI is reserved on a Zenodo *new-version draft* of the
concept record BEFORE release, embedded into source/PDFs/metadata, and the
same draft — never GitHub auto-ingest — is published after the GitHub
release, so exactly one Zenodo record exists per release.

Pure standard library (urllib). Uploads stream from disk (http.client sends
file bodies in small blocks) and retry with bounded exponential backoff on
connection-level failures — the v3.0.1 owl-semaphore release lost a 77 MB
single-shot PUT to a BrokenPipeError that a plain retry would have survived.
Auth via a personal access token with the ``deposit:write`` +
``deposit:actions`` scopes:

    export ZENODO_TOKEN=...            # zenodo.org
    export ZENODO_SANDBOX_TOKEN=...    # sandbox.zenodo.org (use --sandbox)

Publishing is IRREVERSIBLE (a published DOI cannot be deleted). The client
never publishes implicitly; ``ZenodoClient.publish`` must be called
explicitly, and the CLI additionally requires ``--yes``.

IMPORTANT — inherited files: a Zenodo new-version draft starts as a snapshot
of the previous version, INCLUDING its files. Uploading only overwrites
same-named keys; version-tagged filenames (e.g. ``owl-semaphore-v3.0.0.zip``)
from the previous release are silently carried into the new record unless
deleted first. Use :meth:`ZenodoClient.clear_files` (or ``owl-press zenodo
upload --fresh``) before uploading the new release set.
"""

from __future__ import annotations

import http.client
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, BinaryIO, Callable
from urllib.parse import quote

PROD_BASE = "https://zenodo.org"
SANDBOX_BASE = "https://sandbox.zenodo.org"

#: Network timeout (seconds) for the default urllib transport.
DEFAULT_TIMEOUT = 120

#: Upload retry policy: 1 initial attempt + UPLOAD_RETRIES retries, sleeping
#: UPLOAD_BACKOFF * 2**n seconds before retry n. Only connection-level
#: failures (broken pipe, reset, timeout) are retried — the bucket PUT is
#: idempotent and each attempt re-sends the file from the start, so a
#: mid-stream failure cannot leave a corrupt upload. HTTP error responses
#: are never retried.
UPLOAD_RETRIES = 3
UPLOAD_BACKOFF = 2.0

# transport(method, url, headers, body) -> (status, response_bytes).
# body may be bytes or an open binary file (uploads stream from disk).
Transport = Callable[
    [str, str, dict[str, str], "bytes | BinaryIO | None"], tuple[int, bytes]
]


class ZenodoError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _urllib_transport(method: str, url: str, headers: dict[str, str],
                      body: bytes | BinaryIO | None) -> tuple[int, bytes]:
    # A file-like body is streamed by http.client in small blocks; the caller
    # must supply Content-Length, else urllib falls back to chunked
    # Transfer-Encoding, which the Zenodo files API does not accept.
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


class ZenodoClient:
    def __init__(self, token: str, base_url: str = PROD_BASE,
                 transport: Transport | None = None,
                 sleep: Callable[[float], None] | None = None):
        if not token:
            raise ZenodoError("no Zenodo token provided (set ZENODO_TOKEN)")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._transport = transport or _urllib_transport
        self._sleep = time.sleep if sleep is None else sleep

    # -- low-level ---------------------------------------------------------

    def _request(self, method: str, path_or_url: str, json_body: Any = None,
                 raw_body: bytes | BinaryIO | None = None,
                 content_type: str | None = None,
                 content_length: int | None = None) -> Any:
        url = (path_or_url if path_or_url.startswith("http")
               else f"{self.base_url}{path_or_url}")
        headers = {"Authorization": f"Bearer {self.token}"}
        body: bytes | BinaryIO | None = None
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            body = raw_body
            headers["Content-Type"] = content_type or "application/octet-stream"
            if content_length is not None:
                headers["Content-Length"] = str(content_length)

        status, payload = self._transport(method, url, headers, body)
        parsed: Any = None
        if payload:
            try:
                parsed = json.loads(payload.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                parsed = payload
        if status >= 400:
            raise ZenodoError(
                f"Zenodo API {method} {url} failed with HTTP {status}: "
                f"{str(parsed)[:500]}",
                status=status, payload=parsed,
            )
        return parsed

    # -- depositions -------------------------------------------------------

    def get_deposition(self, deposition_id: int | str) -> dict:
        return self._request("GET", f"/api/deposit/depositions/{deposition_id}")

    def list_depositions(self, query: str | None = None) -> list[dict]:
        path = "/api/deposit/depositions"
        if query:
            from urllib.parse import quote

            path += f"?q={quote(query)}"
        return self._request("GET", path)

    def new_version(self, deposition_id: int | str) -> dict:
        """Create (or fetch) the new-version draft of a published deposition.

        Returns the DRAFT deposition. The reserved version DOI is available
        via :meth:`reserved_doi` on the returned draft.
        """
        created = self._request(
            "POST", f"/api/deposit/depositions/{deposition_id}/actions/newversion"
        )
        draft_url = (created.get("links") or {}).get("latest_draft")
        if not draft_url:
            # Some API versions return the draft itself.
            if created.get("state") in ("unsubmitted", "inprogress"):
                return created
            raise ZenodoError(
                "newversion succeeded but no links.latest_draft in response",
                payload=created,
            )
        return self._request("GET", draft_url)

    @staticmethod
    def reserved_doi(deposition: dict) -> str:
        meta = deposition.get("metadata") or {}
        pre = meta.get("prereserve_doi")
        if isinstance(pre, dict) and pre.get("doi"):
            return pre["doi"]
        if deposition.get("doi"):
            return deposition["doi"]
        raise ZenodoError(
            "deposition has no reserved DOI (metadata.prereserve_doi missing)",
            payload=deposition,
        )

    def update_metadata(self, deposition_id: int | str, metadata: dict) -> dict:
        """PUT deposition metadata. ``metadata`` is the Zenodo metadata dict
        (same shape as the ``.zenodo.json`` file's contents)."""
        return self._request(
            "PUT", f"/api/deposit/depositions/{deposition_id}",
            json_body={"metadata": metadata},
        )

    # -- files -------------------------------------------------------------

    def list_files(self, deposition_id: int | str) -> list[dict]:
        return self._request("GET", f"/api/deposit/depositions/{deposition_id}/files")

    def delete_file(self, deposition_id: int | str, file_id: str) -> None:
        """Delete one draft file (new-version drafts inherit the previous
        version's files; stale ones must be deleted before publish)."""
        self._request(
            "DELETE", f"/api/deposit/depositions/{deposition_id}/files/{file_id}"
        )

    def clear_files(self, deposition_id: int | str) -> list[str]:
        """Delete every file currently on the draft. Returns deleted filenames."""
        deleted = []
        for f in self.list_files(deposition_id):
            self.delete_file(deposition_id, f["id"])
            deleted.append(f.get("filename", f.get("key", f["id"])))
        return deleted

    def upload_file(self, deposition: dict, path: str,
                    name: str | None = None) -> dict:
        """Upload one file into the deposition's bucket (new-style files API).

        The file is streamed from disk, never loaded into memory whole. On a
        connection-level failure (broken pipe, reset, timeout) the PUT is
        retried up to UPLOAD_RETRIES times with exponential backoff, re-opened
        from the start each attempt; HTTP error responses raise immediately.
        """
        bucket = (deposition.get("links") or {}).get("bucket")
        if not bucket:
            raise ZenodoError("deposition has no links.bucket", payload=deposition)
        filename = name or os.path.basename(path)
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        # The bucket key is a URL path segment: percent-encode it, otherwise
        # spaces/non-ASCII crash urllib and '#'/'?' silently truncate the key.
        url = f"{bucket}/{quote(filename, safe='')}"
        size = os.path.getsize(path)
        last_exc: Exception | None = None
        for attempt in range(1 + UPLOAD_RETRIES):
            if attempt:
                delay = UPLOAD_BACKOFF * 2 ** (attempt - 1)
                print(f"warning: upload of {filename} interrupted ({last_exc}); "
                      f"retry {attempt}/{UPLOAD_RETRIES} in {delay:g}s",
                      file=sys.stderr)
                self._sleep(delay)
            with open(path, "rb") as f:
                try:
                    return self._request("PUT", url, raw_body=f,
                                         content_type=ctype,
                                         content_length=size)
                except (OSError, http.client.HTTPException) as exc:
                    last_exc = exc
        raise ZenodoError(
            f"upload of {filename} failed after {1 + UPLOAD_RETRIES} attempts: "
            f"{last_exc!r}"
        ) from last_exc

    # -- publish (IRREVERSIBLE) ---------------------------------------------

    def publish(self, deposition_id: int | str) -> dict:
        """Publish the draft. IRREVERSIBLE: the DOI becomes permanent."""
        return self._request(
            "POST", f"/api/deposit/depositions/{deposition_id}/actions/publish"
        )
