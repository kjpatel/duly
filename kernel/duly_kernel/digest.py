"""`decision_digest()` — what was decided, as distinct from which run decided it.

``receiptSha256`` identifies an **artifact**. Two adjudications reaching the
same conclusion, by the same rules, from the same facts, on different machines
or different evaluation backends produce different receipt hashes — correctly,
because they are different artifacts. Nothing could say they were the same
*decision*.

This is that function: SHA-256 over the receipt's determinant fields, in the
same canonical form as every other hash in duly. The determinant set and the
reasoning behind each exclusion are
[spec/compatibility.md](../../spec/compatibility.md) C4; the short version is
that **everything excluded identifies the run rather than the adjudication.**

Two things it deliberately is not.

It is **not a field.** Nothing hashes this value into any document, and nothing
may: the receipt schema is closed (C2), and a digest stored inside the body it
digests is the extension point that document does not have. Keeping it a pure
function is also what keeps the rejected design — a digest field inside the
receipt — recoverable by some future major version, without any committed
artifact having been sealed against it.

It is **not a weaker receipt hash.** Equal digests mean two receipts recorded
the same adjudication; they do not mean either one is authentic. Verifying a
receipt is still ``receiptSha256``, still over the whole body, still the only
thing that resists a forger.
"""

from __future__ import annotations

import hashlib

from duly_core import canonical

__all__ = ["DETERMINANT_FIELDS", "decision_digest", "determinant_projection"]


#: Top-level receipt fields the digest covers, whole.
#:
#: ``rulePack`` and ``engine`` are covered in part and handled below, because
#: each mixes determinant content with run provenance: a pack's identity is its
#: name and version (never where it was fetched from), and the kernel's
#: *semantics* version can change what a decision is while its backend cannot.
DETERMINANT_FIELDS: tuple[str, ...] = (
    "decision",
    "asOf",
    "rulesFired",
    "derivation",
    "inputFacts",
    "abstentions",
)

_RULEPACK_FIELDS: tuple[str, ...] = ("name", "version")
_ENGINE_FIELDS: tuple[str, ...] = ("version",)


def determinant_projection(receipt: dict) -> dict:
    """The sub-document the digest is taken over.

    Exposed because a digest whose input cannot be inspected is a number nobody
    can argue with, and every claim this function makes is an argument about
    which fields belong.

    Raises `KeyError` naming the field if the receipt is missing one. Every
    field here is required by the receipt schema, so an absence means the input
    is not a receipt — and silently digesting a partial document would produce
    a confident answer about something that never happened.
    """
    projection: dict = {}
    for field in DETERMINANT_FIELDS:
        if field not in receipt:
            raise KeyError(f"receipt is missing determinant field {field!r}")
        projection[field] = receipt[field]

    for name, source, fields in (
        ("rulePack", receipt.get("rulePack"), _RULEPACK_FIELDS),
        ("engine", receipt.get("engine"), _ENGINE_FIELDS),
    ):
        if not isinstance(source, dict):
            raise KeyError(f"receipt is missing determinant field {name!r}")
        subset = {}
        for field in fields:
            if field not in source:
                raise KeyError(f"receipt is missing determinant field {name}.{field!r}")
            subset[field] = source[field]
        projection[name] = subset

    return projection


def decision_digest(receipt: dict) -> str:
    """The receipt's decision digest: lowercase hex SHA-256, canonical JSON.

    Two receipts agree — they record the same adjudication — iff their digests
    are equal. Byte equality of the receipts is that *plus* having been
    produced by the same run, which is why cross-backend agreement is defined
    here and not as a byte comparison (C4).
    """
    return hashlib.sha256(canonical(determinant_projection(receipt))).hexdigest()
