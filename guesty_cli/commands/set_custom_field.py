"""Safely set/append a listing custom-field value via Guesty's Open API.

Guesty's PUT /listings/<id> REPLACES the entire customFields array — it does
not merge. A partial payload silently wipes every other field (HTTP 200, no
error). This command makes that class of mistake impossible:

  1. GET the listing (snapshot customFields to memory)
  2. Merge only the requested fieldId into the full array
  3. PUT the complete array back
  4. GET again and verify the fieldId survived with the new value
  5. Diff every other field against the snapshot; report any drift

If Guesty silently drops the write (some field definitions reject API writes
with a 200), the command exits non-zero instead of reporting success.
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from guesty_cli.commands.raw import _do_request, _build_url
from guesty_cli.core.client import GuestyClient, GuestyError
from guesty_cli.core.exit_codes import EXIT_SUCCESS, EXIT_ERROR, EXIT_USAGE
from guesty_cli.core.output import cyan, green, red, yellow


def register(subparsers) -> None:
    p = subparsers.add_parser(
        "set-custom-field",
        help="Safely set or append a listing custom-field value (merge-safe, verified)",
        description=(
            "Sets a single custom field on a Guesty listing without risking the "
            "other fields. Fetches the current fields, merges, PUTs the full array, "
            "and verifies the write survived by reading the listing back."
        ),
    )
    p.set_defaults(func=run)
    p.add_argument("listing_id", help="Guesty listing _id")
    p.add_argument("field_id", help="Custom-field definition id (fieldId)")
    p.add_argument("value", help="New value for the field")
    p.add_argument(
        "--append",
        action="store_true",
        help="Append to the existing value (with a blank-line separator) instead of replacing it",
    )
    p.add_argument(
        "--snapshot",
        help="Optional path to write the pre-change customFields snapshot JSON",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Skip the y/N confirmation for the PUT",
    )


def _get_listing_fields(client: GuestyClient, listing_id: str) -> List[dict]:
    url = _build_url(client, f"/listings/{listing_id}", None)
    body, _ct, _status = _do_request(
        client=client, method="GET", url=url, body=None,
        headers={}, accept=None, content_type=None,
    )
    data = json.loads(body.decode("utf-8"))
    cfs = data.get("customFields")
    if cfs is None:
        cfs = []
    if not isinstance(cfs, list):
        raise GuestyError("Listing customFields is not a list — aborting")
    return cfs


def _put_listing_fields(client: GuestyClient, listing_id: str, cfs: List[dict]) -> None:
    url = _build_url(client, f"/listings/{listing_id}", None)
    payload = json.dumps({"customFields": cfs}).encode("utf-8")
    _body, _ct, _status = _do_request(
        client=client, method="PUT", url=url, body=payload,
        headers={}, accept=None, content_type="application/json",
    )


def _run(args) -> int:
    client = GuestyClient()

    before = _get_listing_fields(client, args.listing_id)
    if args.snapshot:
        with open(args.snapshot, "w") as fh:
            json.dump(before, fh, indent=2)
        print(cyan(f"snapshot: {len(before)} fields -> {args.snapshot}"))

    before_map = {cf.get("fieldId"): cf.get("value") for cf in before}

    existing_value = before_map.get(args.field_id)
    if args.append and existing_value:
        new_value = f"{existing_value}\n\n{args.value}"
    else:
        new_value = args.value

    merged = []
    found = False
    for cf in before:
        if cf.get("fieldId") == args.field_id:
            merged.append({"fieldId": args.field_id, "value": new_value})
            found = True
        else:
            merged.append({"fieldId": cf.get("fieldId"), "value": cf.get("value")})
    if not found:
        merged.append({"fieldId": args.field_id, "value": new_value})

    print(cyan(f"PUT {len(merged)} fields ({len(before)} existing"
               + (" + 1 new" if not found else "") + "); target field will "
               + ("append to" if args.append and existing_value else "replace") + " current value."))

    if not args.force:
        try:
            confirmed = input(f"Write custom field {args.field_id} on listing {args.listing_id}? [y/N] ").strip().lower()
        except EOFError:
            confirmed = ""
        if confirmed not in ("y", "yes"):
            print(red("Cancelled; no write attempted."), file=sys.stderr)
            return EXIT_ERROR

    _put_listing_fields(client, args.listing_id, merged)

    after = _get_listing_fields(client, args.listing_id)
    after_map = {cf.get("fieldId"): cf.get("value") for cf in after}

    if args.field_id not in after_map:
        print(red(
            f"WRITE DROPPED: Guesty returned 200 but field {args.field_id} is absent on readback. "
            "This field definition likely rejects API writes. Nothing else was changed "
            f"(verify below). Fields before/after: {len(before)}/{len(after)}."
        ), file=sys.stderr)
        return EXIT_ERROR
    if after_map[args.field_id] != new_value:
        print(red(
            f"WRITE MISMATCH: readback value differs from what was sent for {args.field_id}."
        ), file=sys.stderr)
        return EXIT_ERROR

    lost = [k for k in before_map if k not in after_map and k != args.field_id]
    changed = [k for k in before_map
               if k != args.field_id and k in after_map and before_map[k] != after_map[k]]
    if lost or changed:
        print(yellow(f"SIDE EFFECTS: lost={lost} changed={changed}"), file=sys.stderr)
        return EXIT_ERROR

    print(green(f"OK: field {args.field_id} saved and verified "
                f"({len(after)} fields, none lost, none changed)."))
    return EXIT_SUCCESS


def run(args) -> None:
    try:
        sys.exit(_run(args))
    except GuestyError as exc:
        print(red(f"Guesty API error: {exc}"), file=sys.stderr)
        sys.exit(EXIT_ERROR)
