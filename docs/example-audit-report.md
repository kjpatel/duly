# Decision audit report

- **Case:** case:policy:HO-77401-NY
- **Question:** Was this termination notice compliant?
- **Verdict:** Not compliant
- **As of (effective):** 2026-07-25T00:00:00Z
- **As of (knowledge):** 2026-07-25T23:59:59Z
- **Rule pack:** termination-notice-us-states v2026.2.0
- **Engine:** duly-kernel v0.0.1 (reference backend)
- **Receipt:** `urn:duly:receipt:sha256:3db9324f5b46ceee908bdd2074b3900edbcb3a897dba7f1e1a37f19e37f7414c`

## Conclusion

For case case:policy:HO-77401-NY, the question "Was this termination notice compliant?" was answered: not compliant. This conclusion was produced by rule NC-NR-01 v1.0.2 under N.Y. Ins. Law § 3425(d)(1). In reaching it, NC-NR-01 overrode the default presumption (NC-DEF-00, which would otherwise have concluded nc:noticeCompliant = true).

## Reasoning

1. New York requires at least 45 days advance notice for nonrenewal of a covered personal-lines policy. (N.Y. Ins. Law § 3425(d)(1)). Under NY-NR-45 v1.1.0, nc:requiredMinimumNoticeDays was determined to be 45.
   — doc:nonrenewal-notice:HO-77401-NY:2026-07-25: "NOTICE OF NONRENEWAL" (fact 491710d4ceb8…)
   — doc:dec-page:HO-77401-NY:2025-09-01: "Insured Location: Albany, New York" (fact 87964b8702ed…)
2. A notice mailed fewer than the required minimum days before the policy expiration is not compliant. (N.Y. Ins. Law § 3425(d)(1)). Under NC-NR-01 v1.0.2, nc:noticeCompliant was determined to be false.
   — doc:dec-page:HO-77401-NY:2025-09-01: "POLICY PERIOD: 09/01/2025 to 09/01/2026" (fact 3a1df6dedacc…)
   — doc:nonrenewal-notice:HO-77401-NY:2026-07-25: "Date of Mailing: July 25, 2026" (fact 3cbbd14b0d2f…)

## Rules applied

### NY-NR-45 v1.1.0 (priority 100)

- **Citation:** N.Y. Ins. Law § 3425(d)(1) — https://www.nysenate.gov/legislation/laws/ISC/3425
- **Effective:** 2026-01-01 → open-ended

### NC-NR-01 v1.0.2 (priority 200)

- **Citation:** N.Y. Ins. Law § 3425(d)(1) — https://www.nysenate.gov/legislation/laws/ISC/3425
- **Effective:** 1986-01-01 → open-ended
- **Defeated:** NC-DEF-00

This rule overrode NC-DEF-00, which would otherwise have concluded nc:noticeCompliant = true.

## Evidence

### nc:policyExpirationDate — fact 3a1df6dedacc…

- **Attribute:** nc:policyExpirationDate
- **Value:** 2026-09-01
- **Document:** doc:dec-page:HO-77401-NY:2025-09-01
- **Page:** 1
- **Character span:** 215–254
- **Quote:** "POLICY PERIOD: 09/01/2025 to 09/01/2026"
- **Extractor:** duly-demo-extractor v0.1.0
- **Assertion kind:** machine
- **Confidence:** 0.995 (conformal)
- **Content hash:** `3a1df6dedacccb8d2e5923d521f357522762d81aa2caddb7dc35f1112866fa90`

### nc:noticeMailedDate — fact 3cbbd14b0d2f…

- **Attribute:** nc:noticeMailedDate
- **Value:** 2026-07-25
- **Document:** doc:nonrenewal-notice:HO-77401-NY:2026-07-25
- **Page:** 1
- **Character span:** 57–87
- **Quote:** "Date of Mailing: July 25, 2026"
- **Extractor:** duly-demo-extractor v0.1.0
- **Assertion kind:** machine
- **Confidence:** 0.989 (conformal)
- **Content hash:** `3cbbd14b0d2f0db140d2eaa86186b3319a7348cfc93d5a95fccab3abb97ca953`

### nc:noticeType — fact 491710d4ceb8…

- **Attribute:** nc:noticeType
- **Value:** Nonrenewal
- **Document:** doc:nonrenewal-notice:HO-77401-NY:2026-07-25
- **Page:** 1
- **Character span:** 35–55
- **Quote:** "NOTICE OF NONRENEWAL"
- **Extractor:** duly-demo-extractor v0.1.0
- **Assertion kind:** machine
- **Confidence:** 0.972 (conformal)
- **Content hash:** `491710d4ceb800550d2999d260021f7135a07f56e7f0c1f2a926a0e8ba30d115`

### nc:governingState — fact 87964b8702ed…

- **Attribute:** nc:governingState
- **Value:** US-NY
- **Document:** doc:dec-page:HO-77401-NY:2025-09-01
- **Page:** 1
- **Character span:** 179–213
- **Quote:** "Insured Location: Albany, New York"
- **Extractor:** duly-demo-extractor v0.1.0
- **Assertion kind:** machine
- **Confidence:** 0.998 (conformal)
- **Content hash:** `87964b8702ed931b43879d0f3c2bbaadd8cdfdd800ebf0d981a15be9cb66ba76`

## Integrity and replay

- **Receipt SHA-256:** `3db9324f5b46ceee908bdd2074b3900edbcb3a897dba7f1e1a37f19e37f7414c`

This receipt is content-addressed: receiptSha256 is the SHA-256 of the receipt's RFC 8785-style canonical JSON (sorted keys, minimal separators, UTF-8), excluding the id and receiptSha256 fields themselves. Any alteration to the receipt changes its hash.

Every input fact is content-addressed the same way: each fact's id is urn:duly:fact:sha256:<contentHash>, so the facts this decision consumed can be verified byte-for-byte against the hashes pinned in inputFacts.

To replay this decision:

```
uv run python -m duly_kernel \
    --facts <directory of the facts pinned in inputFacts> \
    --pack rulepacks/termination-notice-us-states/pack.yaml \
    --asof 2026-07-25T00:00:00Z \
    --asof-knowledge 2026-07-25T23:59:59Z \
    --question nc:noticeCompliant
```

The facts directory must contain exactly the facts pinned in inputFacts (matched by content hash); any other fact set is a different adjudication.

Engine: duly-kernel v0.0.1, reference backend.

Determinism statement: this report is a pure rendering of the receipt, its input facts, and the rule pack. Re-rendering the same inputs produces a byte-identical report; re-running the engine on the pinned facts, pack version, and asOf pair reproduces the same receipt hash.
