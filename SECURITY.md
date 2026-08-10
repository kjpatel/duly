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

Only `main` and the latest tagged release are supported. There are no backported
fixes: a security fix lands on `main` and, when it warrants one, in a new
release tagged from it.

## Dependencies

The document→receipt path depends on `pyyaml` and the standard library, and so does
the default install: `pip install duly` brings exactly two packages, duly and
PyYAML. Everything else — the HTTP surfaces (`duly[demo]`, which covers both the
demonstration workspace and the review queue's API), the PDF report renderer
(`duly[report]`), the extraction stack (`duly[extraction]`), the SMT solver behind
`prove` and `whatif` (`duly[prove]`) — is behind an optional extra, so a kernel-only
integration does not inherit their surface. The example that plans a closing with
CP-SAT declares its own solver in the example, not in duly.

That two is asserted, not asserted-to:
[`examples/minimal-integration/check_wheel.sh`](examples/minimal-integration/check_wheel.sh)
installs a built wheel into a clean virtualenv, runs the example against it with
duly's source tree off `sys.path`, and fails if the install brought a third package.

That gap is closed as of 1.0.0: `jsonschema` is a core dependency, because the
review queue's correction validation enforces a compatibility rule
([spec/compatibility.md](spec/compatibility.md) C6), and enforcement of a
compatibility rule is not behaviour an optional extra may withhold. A plain
install is duly, pyyaml, and jsonschema's small closure — seven packages, still
pinned by the wheel check.
