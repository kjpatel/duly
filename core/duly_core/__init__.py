"""Canonical form and content addressing. Nothing else, ever.

**This package has a deliberately narrow charter.** It holds the two functions
that decide what a duly document's bytes *are* — `canonical` and
`content_hash` — because every other package needs them and none of them may
disagree. It is not a utilities package, and it must not become one: the next
"small shared helper" that lands here starts the drift toward a junk drawer,
and the reason this package can be depended on by every other is precisely
that it is tiny, dependency-free, and finished.

Before this existed, `content_hash` was implemented **seven times** across the
repository, under three different signatures. They all agreed — that was
measured, not assumed — but agreement between copies is not verification. It
proves nobody typed it wrong; it cannot tell you whether the definition is
right. That is what `spec/canonical-vectors.json` is for: the oracle is the
specification and a set of committed vectors, never a sibling copy.

## The canonical form

    json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

over the document's own bytes as UTF-8, with the document's `id` and its hash
field excluded. Four properties, each load-bearing:

- **sorted keys** so two writers of the same facts produce the same bytes;
- **minimal separators** so whitespace cannot change identity;
- **no ASCII escaping** so a quote containing an em dash or an accented name
  hashes the same everywhere (`ensure_ascii=True` would emit `\\u2014` and
  give a different digest for identical content);
- **the id and hash excluded**, so the hash is over what the document *says*,
  and re-sealing is idempotent rather than a second identity.

Key ordering follows [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785) (JSON
Canonicalization Scheme): UTF-16 code-unit order, which is what the fact and
receipt schemas claim. Python's `sort_keys=True` sorts by *code point*, which
differs for non-BMP characters — an emoji key sorts after a private-use BMP key
under Python and before it under RFC 8785 — so this module sorts explicitly
rather than relying on `sort_keys`. See `spec/canonical-vectors.json`.
"""

from __future__ import annotations

import hashlib
import json

__all__ = ["canonical", "content_hash", "canonical_key"]

__version__ = "0.0.1"


def canonical_key(key: str) -> bytes:
    """RFC 8785 object-key sort order: UTF-16 code units, big-endian.

    Python's `sorted()` and `json.dumps(sort_keys=True)` order strings by
    Unicode code point. RFC 8785 §3.2.3 orders object keys by their UTF-16
    representation, and the two disagree above the BMP: a code point over
    U+FFFF encodes as a surrogate pair in 0xD800–0xDFFF, which sorts *before*
    BMP characters from U+E000 up, and *after* them by code point.

    No committed duly document has a non-ASCII object key — every hashed
    document has fixed schema field names — so this changes no existing hash.
    It is here so the schemas' "RFC 8785" is a fact rather than an
    approximation, and so an implementation in another language can be held to
    the same rule.
    """
    return key.encode("utf-16-be")


def canonical(obj) -> bytes:
    """The canonical UTF-8 bytes of `obj`. See the module docstring."""
    return json.dumps(
        _sorted(obj), sort_keys=False, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sorted(obj):
    """Recursively reorder every object's keys into RFC 8785 order.

    Done here rather than with `sort_keys=True` because that sorts by code
    point; see `canonical_key`. Lists keep their order — JSON array order is
    data, not presentation.
    """
    if isinstance(obj, dict):
        return {k: _sorted(obj[k]) for k in sorted(obj, key=canonical_key)}
    if isinstance(obj, list):
        return [_sorted(v) for v in obj]
    return obj


def content_hash(doc: dict, hash_field: str) -> str:
    """SHA-256 over `doc`'s canonical bytes, excluding `id` and `hash_field`.

    `hash_field` is explicit and has no default on purpose. Facts carry
    `contentHash`, receipts carry `receiptSha256`, and envelopes their own —
    a default would let a caller hash a receipt as though it were a fact and
    get a plausible, wrong digest with nothing to catch it.
    """
    body = {k: v for k, v in doc.items() if k not in ("id", hash_field)}
    return hashlib.sha256(canonical(body)).hexdigest()
