# Security policy

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub's
[security advisory form](https://github.com/kjpatel/duly/security/advisories/new),
which is the fastest route and keeps the report confidential until a fix exists.

Expect an acknowledgement within a week. duly is a pre-1.0 project maintained by one
person; there is no on-call rotation and no paid bounty, and saying so plainly is
better than implying a response time nobody staffs.

## Scope

duly is a **library and reference wiring**, not a hosted service. What is in scope:

- anything that lets an attacker forge a receipt that passes verification, or make a
  tampered fact, envelope or receipt verify as intact;
- a path traversal or arbitrary file read/write in code that accepts caller data —
  notably the demo's `/api/receipts/inspect`, which takes a `rulePack.name` from a
  pasted document and joins it into a path;
- code execution reachable from parsing a document, fact, receipt, rule pack, DMN
  file or ontology;
- a way to make the kernel produce a decision that its own receipt does not justify.

What is **out of scope**, because it is a documented property rather than a defect:

- **The demo server has no authentication, and no CSRF or rate limiting.** It binds
  localhost, ships example content, and is a demonstration surface. Do not deploy it.
- **`adjudicate()` trusts the fact list it is given.** Schema validation, envelope
  verification and ontology conformance are composed by the deployment's admission
  path; the kernel deliberately does not repeat them
  ([architecture guide](docs/neuro-symbolic-architecture.md), §3).
- **Content addressing is tamper-*evidence*, not authenticity.** Anyone who alters a
  receipt can re-seal it, and the re-sealed document passes every check that treats
  it as a document — only re-adjudication refuses it. This is stated at length in
  [spec/compatibility.md](spec/compatibility.md) and the architecture guide, and it
  is why receipt verification reports three independent checks rather than one
  verdict.
- **There is no authenticity claim about *who* produced an extraction run.**
  Envelope signatures are a designed-but-unimplemented affordance; the shape is
  settled ([compatibility.md](spec/compatibility.md) C7), the scheme is not.

A report that a documented boundary exists is not a vulnerability report — but a
report that a boundary is *wrong*, or that the documentation misstates what a check
actually establishes, is very welcome and is the most valuable thing this policy
can attract.

## Supported versions

Pre-1.0: only `main` is supported. There are no backported fixes and no published
distribution yet.

## Dependencies

The document→receipt path depends on `pyyaml` and the standard library. Everything
else — the demo server, the PDF report renderer, the solver, the extraction stack —
is behind an optional extra or a marker-gated test, so a kernel-only integration
does not inherit their surface. Reducing the default install to exactly that set is
tracked M5 work; today `pip install`-equivalent pulls more than the kernel needs.
