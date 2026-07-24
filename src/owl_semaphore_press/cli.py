"""owl-press — CLI for the Owl Semaphore publishing toolchain.

Subcommands (Zenodo release automation, per RELEASE-PROCESS.md):

  owl-press zenodo new-version DEPOSITION_ID
      Create/fetch the new-version draft of a published deposition and print
      the draft id + reserved version DOI (the value to embed in source).

  owl-press zenodo metadata DEPOSITION_ID --from .zenodo.json
      Push metadata from a .zenodo.json file onto the draft.

  owl-press zenodo upload DEPOSITION_ID FILE [FILE ...]
      Upload release files into the draft's bucket.

  owl-press zenodo files DEPOSITION_ID
      List files currently on the deposition.

  owl-press zenodo status DEPOSITION_ID
      Show state, DOI, and links for a deposition.

  owl-press zenodo publish DEPOSITION_ID --yes
      Publish the draft. IRREVERSIBLE; refuses to run without --yes.

Global flags: --sandbox (use sandbox.zenodo.org + ZENODO_SANDBOX_TOKEN),
--token TOKEN (overrides the environment).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .zenodo import PROD_BASE, SANDBOX_BASE, ZenodoClient, ZenodoError


def _client(args: argparse.Namespace) -> ZenodoClient:
    if args.sandbox:
        token = args.token or os.environ.get("ZENODO_SANDBOX_TOKEN", "")
        base = SANDBOX_BASE
    else:
        token = args.token or os.environ.get("ZENODO_TOKEN", "")
        base = PROD_BASE
    if not token:
        var = "ZENODO_SANDBOX_TOKEN" if args.sandbox else "ZENODO_TOKEN"
        print(f"error: no token (set {var} or pass --token)", file=sys.stderr)
        raise SystemExit(2)
    return ZenodoClient(token, base_url=base)


def _cmd_new_version(args: argparse.Namespace) -> int:
    client = _client(args)
    draft = client.new_version(args.deposition_id)
    doi = client.reserved_doi(draft)
    print(f"draft deposition id : {draft.get('id')}")
    print(f"reserved version DOI: {doi}")
    print(f"draft URL           : {(draft.get('links') or {}).get('html', '?')}")
    print()
    print("Next: embed the reserved DOI in source/PDFs/metadata, rebuild, then")
    print("`owl-press zenodo upload` + `owl-press zenodo publish --yes`.")
    return 0


def _cmd_metadata(args: argparse.Namespace) -> int:
    client = _client(args)
    with open(args.from_file, "r", encoding="utf-8") as f:
        metadata = json.load(f)
    # A .zenodo.json file IS the metadata dict.
    updated = client.update_metadata(args.deposition_id, metadata)
    print(f"metadata updated on deposition {updated.get('id')}")
    return 0


def _cmd_upload(args: argparse.Namespace) -> int:
    client = _client(args)
    dep = client.get_deposition(args.deposition_id)
    for path in args.files:
        if not os.path.isfile(path):
            print(f"error: not a file: {path}", file=sys.stderr)
            return 2
    for path in args.files:
        client.upload_file(dep, path)
        print(f"uploaded {path}")
    return 0


def _cmd_files(args: argparse.Namespace) -> int:
    client = _client(args)
    for f in client.list_files(args.deposition_id):
        print(f"{f.get('filename', f.get('key', '?'))}\t{f.get('filesize', f.get('size', '?'))}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    client = _client(args)
    dep = client.get_deposition(args.deposition_id)
    meta = dep.get("metadata") or {}
    pre = meta.get("prereserve_doi") or {}
    print(f"id      : {dep.get('id')}")
    print(f"state   : {dep.get('state')}")
    print(f"title   : {meta.get('title', '?')}")
    print(f"version : {meta.get('version', '?')}")
    print(f"DOI     : {dep.get('doi') or pre.get('doi', '(none)')}")
    print(f"html    : {(dep.get('links') or {}).get('html', '?')}")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    if not args.yes:
        print("refusing to publish without --yes.", file=sys.stderr)
        print("Publishing is IRREVERSIBLE: the DOI becomes permanent and the "
              "record cannot be deleted.", file=sys.stderr)
        return 2
    client = _client(args)
    published = client.publish(args.deposition_id)
    print(f"published: {published.get('doi', '?')}")
    print(f"record   : {(published.get('links') or {}).get('record_html', '?')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="owl-press")
    parser.add_argument("--sandbox", action="store_true",
                        help="use sandbox.zenodo.org (ZENODO_SANDBOX_TOKEN)")
    parser.add_argument("--token", default=None, help="Zenodo API token")
    sub = parser.add_subparsers(dest="command", required=True)

    zen = sub.add_parser("zenodo", help="Zenodo release automation")
    zsub = zen.add_subparsers(dest="zenodo_command", required=True)

    p = zsub.add_parser("new-version", help="create new-version draft, print reserved DOI")
    p.add_argument("deposition_id")
    p.set_defaults(func=_cmd_new_version)

    p = zsub.add_parser("metadata", help="push metadata from a .zenodo.json file")
    p.add_argument("deposition_id")
    p.add_argument("--from", dest="from_file", required=True,
                   help="path to .zenodo.json")
    p.set_defaults(func=_cmd_metadata)

    p = zsub.add_parser("upload", help="upload files into the draft bucket")
    p.add_argument("deposition_id")
    p.add_argument("files", nargs="+")
    p.set_defaults(func=_cmd_upload)

    p = zsub.add_parser("files", help="list deposition files")
    p.add_argument("deposition_id")
    p.set_defaults(func=_cmd_files)

    p = zsub.add_parser("status", help="show deposition state and DOI")
    p.add_argument("deposition_id")
    p.set_defaults(func=_cmd_status)

    p = zsub.add_parser("publish", help="publish the draft (IRREVERSIBLE)")
    p.add_argument("deposition_id")
    p.add_argument("--yes", action="store_true",
                   help="confirm irreversible publication")
    p.set_defaults(func=_cmd_publish)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ZenodoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
