"""What `import duly_kernel` gives you, and why it is that and not more.

Content addressing is the first thing an integration touches: a fact must be
sealed before anything can consume it. It used to live only at
`duly_kernel.receipt`, a module path that reads private, so every adopter
either reached into it or wrote their own three-line variant — and a private
variant produces facts nobody else can verify (docs/m5-plan.md, A1).
"""

from __future__ import annotations

import duly_kernel
from duly_kernel import content_hash, seal_fact


def test_the_first_contact_api_is_at_the_package_root():
    assert duly_kernel.__all__ == ["adjudicate", "content_hash", "seal_fact"]


def test_seal_fact_derives_the_id_from_the_hash():
    sealed = seal_fact({"caseId": "c1", "attribute": "ex:a"})
    assert sealed["id"] == f"urn:duly:fact:sha256:{sealed['contentHash']}"


def test_seal_fact_is_idempotent():
    """Re-sealing must not change the digest, or a pipeline that seals twice
    silently produces two identities for one fact."""
    once = seal_fact({"caseId": "c1", "attribute": "ex:a"})
    assert seal_fact(once) == once


def test_seal_fact_ignores_a_stale_hash_rather_than_trusting_it():
    """A fact arriving with someone else's contentHash is re-derived from its
    bytes. Trusting the field would make the seal a claim instead of a check."""
    stale = {"caseId": "c1", "attribute": "ex:a", "id": "urn:duly:fact:sha256:" + "0" * 64,
             "contentHash": "0" * 64}
    resealed = seal_fact(stale)
    assert resealed["contentHash"] != "0" * 64
    assert resealed == seal_fact({"caseId": "c1", "attribute": "ex:a"})


def test_seal_fact_agrees_with_content_hash():
    """The helper must be exactly the long way round, or an author who checks
    by hand gets a different answer than the one who used the helper."""
    fact = {"caseId": "c1", "attribute": "ex:a"}
    assert seal_fact(fact)["contentHash"] == content_hash(fact, "contentHash")


def test_the_canonical_form_does_not_escape_non_ascii():
    """`ensure_ascii=False` is load-bearing and easy to drop when
    reimplementing: a document quoting an em dash or an accented name would
    otherwise hash two different ways depending on who sealed it."""
    fact = {"caseId": "c1", "quote": "Ríos — 45 days"}
    body = '{"caseId":"c1","quote":"Ríos — 45 days"}'
    import hashlib

    assert content_hash(fact, "contentHash") == hashlib.sha256(
        body.encode("utf-8")
    ).hexdigest()
