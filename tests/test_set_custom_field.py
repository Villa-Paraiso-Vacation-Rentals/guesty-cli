"""Unit tests for the set-custom-field command (no network).

Exercises merge/snapshot logic by stubbing _get_listing_fields/_put_listing_fields.
"""

import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guesty_cli.commands import set_custom_field as scf


def _args(**kw):
    return mock.MagicMock(
        listing_id="L1", field_id="F1", value="new",
        append=kw.get("append", False), snapshot=None, force=True,
    )


def test_merge_preserves_other_fields_and_verifies():
    before = [
        {"fieldId": "A", "value": "keep-a"},
        {"fieldId": "F1", "value": "replace-me"},
    ]
    state = {"value": before}

    def fake_get(client, listing_id):
        return json.loads(json.dumps(state["value"]))

    def fake_put(client, listing_id, cfs):
        state["value"] = cfs  # server stores exactly what was PUT

    with mock.patch.object(scf, "_get_listing_fields", fake_get), \
         mock.patch.object(scf, "_put_listing_fields", fake_put):
        rc = scf._run(_args())

    assert rc == 0
    assert state["value"][0] == {"fieldId": "A", "value": "keep-a"}
    assert state["value"][1] == {"fieldId": "F1", "value": "new"}


def test_append_mode_keeps_existing_value():
    before = [{"fieldId": "F1", "value": "original"}]
    state = {"value": before}

    def fake_get(client, listing_id):
        return json.loads(json.dumps(state["value"]))

    def fake_put(client, listing_id, cfs):
        state["value"] = cfs

    args = _args(append=True)
    with mock.patch.object(scf, "_get_listing_fields", fake_get), \
         mock.patch.object(scf, "_put_listing_fields", fake_put):
        rc = scf._run(args)

    assert rc == 0
    assert state["value"] == [{"fieldId": "F1", "value": "original\n\nnew"}]


def test_silent_drop_is_failure():
    before = [{"fieldId": "A", "value": "keep"}]
    state = {"value": before}

    def fake_get(client, listing_id):
        # Server silently drops F1 writes: readback never contains it
        return json.loads(json.dumps(state["value"]))

    def fake_put(client, listing_id, cfs):
        state["value"] = [cf for cf in cfs if cf["fieldId"] != "F1"]

    with mock.patch.object(scf, "_get_listing_fields", fake_get), \
         mock.patch.object(scf, "_put_listing_fields", fake_put):
        rc = scf._run(_args())

    assert rc != 0  # must NOT report success when the write was dropped


def test_side_effect_on_other_field_is_failure():
    before = [{"fieldId": "A", "value": "keep"}, {"fieldId": "F1", "value": "old"}]
    state = {"value": before}

    def fake_get(client, listing_id):
        return json.loads(json.dumps(state["value"]))

    def fake_put(client, listing_id, cfs):
        # Server side effect: field A lost
        state["value"] = [cf for cf in cfs if cf["fieldId"] != "A"]

    with mock.patch.object(scf, "_get_listing_fields", fake_get), \
         mock.patch.object(scf, "_put_listing_fields", fake_put):
        rc = scf._run(_args())

    assert rc != 0
