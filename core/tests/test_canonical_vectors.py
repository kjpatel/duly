"""The canonical form, verified against its specification rather than a copy.

There used to be seven implementations of `content_hash` in this repository,
and a plan to keep them and test that they agreed. That test would have been
worth very little: the seven were three identical lines calling the same
stdlib function, so they had no algorithmic diversity and their agreement
could only ever have proved that nobody typed it wrong. It would also have
been actively misleading, because it borrows the look of duly's real
differential checks — `prove`'s SMT solving against `validate_pack`'s
syntactic matching, the evidence browser's log replay against the store's
survivor projection — which compare genuinely different mechanisms.

So the oracle here is the *specification*. Two layers:

1. `spec/canonical-vectors.json` is a frozen baseline and an interop artifact
   — it catches silent change and tells another language exactly what to
   produce. Being generated from this implementation, it cannot prove the
   implementation right.
2. The property tests below recompute what RFC 8785 requires, independently of
   `duly_core`, and hold the implementation to it. This is the part that can
   find a bug rather than a regression.
"""

from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from duly_core import canonical, content_hash

VECTORS_PATH = pathlib.Path(__file__).resolve().parents[2] / "spec" / "canonical-vectors.json"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]
IDS = [v["description"] for v in VECTORS]


# --- layer 1: the frozen baseline -------------------------------------------


@pytest.mark.parametrize("vector", VECTORS, ids=IDS)
def test_the_implementation_reproduces_every_committed_vector(vector):
    document, field = vector["document"], vector["hashField"]
    body = {k: v for k, v in document.items() if k not in ("id", field)}
    assert canonical(body).decode("utf-8") == vector["canonical"]
    assert content_hash(document, field) == vector["sha256"]


def test_every_vector_hash_is_sha256_of_its_own_canonical_bytes():
    """The two committed columns must not be able to drift apart."""
    for vector in VECTORS:
        expected = hashlib.sha256(vector["canonical"].encode("utf-8")).hexdigest()
        assert vector["sha256"] == expected, vector["description"]


# --- layer 2: the properties RFC 8785 actually requires ---------------------


def _utf16_sorted(keys):
    """RFC 8785 §3.2.3 key order, computed here rather than imported."""
    return sorted(keys, key=lambda k: k.encode("utf-16-be"))


@pytest.mark.parametrize(
    "document",
    [
        {"b": 1, "a": 2},
        {"\U0001f600": 1, "\ue000": 2},   # non-BMP vs BMP private use
        {"z": 1, "é": 2, "a": 3},          # accented Latin among ASCII
        {"\u007f": 1, "0": 2, "~": 3},
    ],
)
def test_keys_are_in_utf16_code_unit_order(document):
    """Python's `sort_keys=True` orders by code point, which is *not* this.

    They agree for BMP-only keys and disagree above it: a code point over
    U+FFFF encodes as a surrogate pair in 0xD800-0xDFFF, so it sorts before
    BMP characters from U+E000 up under RFC 8785, and after them under Python.
    """
    emitted = json.loads(canonical(document).decode("utf-8"))
    assert list(emitted) == _utf16_sorted(document)


def test_the_non_bmp_case_is_one_python_would_get_wrong():
    """Pins the divergence, so this stops being a claim about Python."""
    document = {"\U0001f600": 1, "\ue000": 2}
    ours = list(json.loads(canonical(document).decode("utf-8")))
    pythons = list(json.loads(json.dumps(document, sort_keys=True, ensure_ascii=False)))
    assert ours == _utf16_sorted(document)
    assert ours != pythons


def test_no_whitespace_survives_canonicalization():
    blob = canonical({"a": {"b": [1, 2]}, "c": "d"}).decode("utf-8")
    assert blob == '{"a":{"b":[1,2]},"c":"d"}'


def test_non_ascii_is_never_escaped():
    """`ensure_ascii=True` would emit \\u2014 and give a different digest for
    identical content — the single easiest way to break interoperability."""
    blob = canonical({"q": "Ríos — 45 days"}).decode("utf-8")
    assert "Ríos — 45 days" in blob
    assert "\\u" not in blob


def test_array_order_is_preserved():
    """JSON array order is data. Sorting it would change meaning, not form."""
    assert canonical({"xs": ["b", "a", "c"]}).decode("utf-8") == '{"xs":["b","a","c"]}'


def test_only_top_level_id_and_hash_field_are_excluded():
    """A nested `id` is ordinary data — excluding it would silently drop
    content from the hash."""
    nested = {"caseId": "c1", "entity": {"id": "claim:1", "type": "ex:Claim"}}
    assert '"id":"claim:1"' in canonical(nested).decode("utf-8")


def test_the_hash_field_argument_is_required():
    """No default: facts carry `contentHash`, receipts `receiptSha256`. A
    default lets a caller hash a receipt as a fact and get a plausible,
    wrong digest with nothing to catch it."""
    with pytest.raises(TypeError):
        content_hash({"caseId": "c1"})  # type: ignore[call-arg]


def test_encoding_is_utf8_bytes_not_str():
    assert isinstance(canonical({"a": 1}), bytes)
