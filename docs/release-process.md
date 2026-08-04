# Cutting a release

Who this is for: whoever — human or agent — is about to bump a version, tag a
commit, or answer "is this change breaking?" It is a decision procedure, not a
narrative. Read §1 and §2, then find your change in §3.

The one-sentence version: **duly has four independent version scopes, and the
instinct to make them agree is the most destructive edit available in this
repository.** Aligning `engine.version` with a package number invalidates all
351 golden receipts without a rule, a fact, or a decision having changed.

Sections marked **PENDING** record a decision that has not been made yet. They
are here so the gap is visible at the moment it matters, not so they can be
guessed at. Resolving them is M5 Phase 2 work and lands in `spec/compatibility.md`.

---

## 1. The version surface

Ten version declarations, four scopes. Only two have a reader.

| Site | Scope | Read by |
|---|---|---|
| [`pyproject.toml`](../pyproject.toml) `version` | distribution | packaging, `pip show duly` |
| [`receipt.py`](../kernel/duly_kernel/receipt.py) `SEMANTICS_VERSION` | decision semantics | **every receipt hash** |
| [`kernel/duly_kernel/__init__.py`](../kernel/duly_kernel/__init__.py) `__version__` | kernel package | nothing |
| `store`, `assurance`, `calibration`, `review`, `extraction`, `core` `__init__.py` | package | nothing |
| [`demo/app.py`](../demo/app.py) `FastAPI(version=…)` | HTTP API | the OpenAPI document |
| [`review/duly_review/api.py`](../review/duly_review/api.py) `FastAPI(version=…)` | HTTP API | the OpenAPI document |

The scopes nest **one way only**:

```
semantics change  ⇒  kernel code change  ⇒  distribution release
```

Never the reverse. A release can be a demo fix with the kernel byte-identical;
a kernel refactor can leave every decision exactly as it was. That asymmetry is
the whole reason these are separate numbers.

All of them read `0.0.1` today. That is a coincidence of history, and it is
precisely what makes a re-coupling invisible — see
[`test_engine_identity.py`](../kernel/tests/test_engine_identity.py), which
proves the decoupling behaviourally because nothing else can while the values
agree.

**PENDING** — six of the package `__version__` strings have no reader, and
three packages (`conformance`, `dmn`, `whatif`) declare none at all, so the
convention is already inconsistent. Either give them a reader and a rule or
delete them; a number nobody reads and nothing forces to move becomes a lie.

## 2. Version schemes in use

- **Distribution** — semver. `MAJOR.MINOR.PATCH`.
- **Semantics** (`SEMANTICS_VERSION`) — semver-shaped, but it is a *handle*
  rather than an ordering claim. See §4.
- **Rule packs** — `pack.version`, calendar-led: `2026.1.0`, `2026.2.0`,
  `2026.3.0`. Set per pack, independent of everything above.
  **PENDING**: the scheme is observed convention, not documented rule — what
  the second and third components mean has never been written down.
- **Ontologies** — `<name>/<version>.yaml`, **immutable once committed**. New
  terms go in a new version file and the facts re-pin to it
  ([ontologies/README.md](../ontologies/README.md)).

## 3. Which numbers move?

Find the change you made. Where a row says a number does *not* move, that is
load-bearing, not an omission.

| You changed | Distribution | Kernel pkg | `SEMANTICS_VERSION` | Other |
|---|---|---|---|---|
| Docs, tests, CI only | patch | — | — | — |
| Demo page, static assets | patch | — | — | demo `FastAPI(version=)` if the HTTP surface moved |
| A non-kernel package (`store`, `review`, `calibration`, …) | patch or minor | — | — | — |
| Kernel code, **golden replay still green** | patch or minor | yes | **no** | — |
| Kernel code, **golden replay breaks, packs and facts unchanged** | minor or major | yes | **yes** — see §4 | corpus regeneration |
| A rule pack's rules | patch | — | — | `pack.version`; impact analysis |
| A pack's `phrasing:` / `question` | patch | — | — | nothing hashed moves |
| Added an ontology term | patch | — | — | new ontology version file; facts re-pin; **fact hashes change ⇒ corpus churn** |
| New optional dependency + extra | minor | — | — | pytest marker, optional-deps workflow |
| Receipt, fact, or IR **schema** | major | — | see §4 | breaking — §5 |
| A new public Python API | minor | yes if in kernel | — | — |
| Removed or renamed a public API | major | yes if in kernel | — | — |

Two rows deserve emphasis because they are counterintuitive:

**A kernel bugfix is usually a semantics change.** If the evaluator was wrong
and you corrected it, decisions move — that is the point of the fix — and the
corrected behaviour is new semantics. "It was a bug" is a reason the change is
*right*, not a reason it is invisible.

**A pack change never touches a package version.** Packs are versioned data.
The kernel that reads them did not change.

## 4. Revving `SEMANTICS_VERSION`

### The discriminator

Nothing forces this number to move when the kernel's meaning moves — except
the corpus, which is already in CI. The rule:

> Golden bytes moved **and** packs unchanged **and** facts unchanged
> ⇒ the kernel's meaning changed ⇒ `SEMANTICS_VERSION` moves with it.

So the procedure after any kernel change is mechanical:

```bash
uv run python -m duly_assurance verify
```

Green → not a semantics change; bump the kernel package if its code moved and
stop. Red → check the diff for pack or fact changes. If there are none, you
have changed what the kernel *means*, and there are exactly two honest
responses: revert (the change was a mistake), or rev the semantics and accept
the consequences below.

Making `verify` pass by regenerating the corpus, without revving the semantics,
is the one move this document exists to prevent.

### What a rev costs

1. **Every committed receipt stops replaying under the new kernel.** This is
   correct, not collateral damage: a receipt sealed under semantics X should
   not be reproducible under semantics Y. If it were, the bump would be a lie.
2. **The corpus is regenerated** under the new semantics — the reviewed,
   deliberate act described in [golden/README.md](../golden/README.md), with
   `impact` run and every flip justified in the PR.
3. **Old receipts remain valid documents.** Their hashes are intact and they
   say exactly what they said. What they lose is replayability under a kernel
   that no longer implements their semantics.

### The replay guarantee

**PENDING** — the clause that makes a rev survivable does not exist yet.
The intended shape:

> A receipt sealed under semantics version V replays byte-identically under any
> kernel implementing V. A kernel MAY implement more than one V. A semantics
> change is a new V; the corpus carries cases at every V the project still
> promises to replay.

That converts "the corpus breaks on a semantics change" into an ordinary
support-window question. Until it is written down and a support window is
chosen, **treat a semantics rev as blocked** and escalate rather than
improvising one.

## 5. What counts as breaking

Per contract, because they break differently.

| Contract | Breaking means | Detected by |
|---|---|---|
| **Fact** ([schema](../core/duly_core/schemas/grounded-fact.schema.json)) | any change to hashed bytes; adding a field (`additionalProperties: false`) | `spec/validate.py`, conformance sweep |
| **Receipt** ([schema](../core/duly_core/schemas/decision-receipt.schema.json)) | same — the hash covers the whole body, so *there is no additive change* | `verify` |
| **Rule IR** ([spec](../spec/rule-ir.md)) | a pack that used to load no longer does, or loads and means something else | `kernel/tests/test_rulepacks.py`, `expected.yaml` |
| **Pack** | rules changed such that historical decisions move | `impact` (the CI comment) |
| **Ontology** | editing a committed version file — never do this | `conformance/tests/test_repo_conformance.py` |
| **HTTP API** | a removed route, a renamed field, a changed status code | nothing automated today |
| **Python API** | a removed or renamed public symbol | nothing automated today |

The receipt row is the unusual one and worth internalising: because the hash
covers the entire body, **"additive and backward-compatible" does not exist for
receipts.** Every candidate new field is a breaking change. Anything that wants
to travel alongside a receipt travels in a separately-hashed sidecar that
references it — the idiom [PROV-O export](../spec/prov-o.md) already
established: *wrap, never edit*.

## 6. Tagging

Tags are **annotated**, named `vMAJOR.MINOR.PATCH`, with the milestone as the
subject:

```bash
git tag -a v0.5.0 -m "M5: adoption and v1.0"
git push origin v0.5.0
```

Existing tags: `v0.1.0` (M0/M1), `v0.2.0` (M2), `v0.3.0` (M3), `v0.4.0` (M4).

**What a tag has meant so far:** a milestone marker, explicitly *not* a package
release — [CHANGELOG.md](../CHANGELOG.md) says so, and `pyproject.toml`
deliberately stayed at `0.0.1` because nothing was published. A tag said "this
milestone is done and here is what it meant"; it did not say the contract was
stable.

**What changes at M5:** the distribution is published, so a tag becomes both.
From that point the tag and `pyproject.toml` `version` must agree, and the
distinction between "milestone done" and "contract stable" has to be carried by
`spec/compatibility.md` instead of by the absence of a package.

Tag only after §7 is green on the commit you are tagging.

## 7. The release checklist

In order. Do not reorder — the cheap checks are first on purpose.

```bash
uv sync
uv run pytest core/tests kernel/tests demo/tests assurance/tests store/tests calibration/tests extraction/tests review/tests conformance/tests dmn/tests whatif/tests -q
uv run python -m duly_assurance verify
uv run spec/validate.py
uv run python3 starters/tools/check_facts.py
uv run python -m duly_conformance --ontologies ontologies check starters golden/cases rulepacks spec/examples
uv run python -m duly_assurance impact
```

The main `pytest` line **skips every marker-gated test** — four
optional-dependency markers, spread across six suites. They run in
[optional-deps.yml](../.github/workflows/optional-deps.yml), but a release must
not rely on a path filter having triggered:

```bash
uv run --with linkml --with pyshacl pytest conformance/tests -q -m linkml
uv sync --extra prove && uv run pytest assurance/tests whatif/tests demo/tests -q -m z3
uv sync --extra scheduling && uv run pytest examples/closing-scheduler -q -m ortools
uv sync --extra extraction && uv run pytest extraction/tests -q -m docling
```

Then, before tagging:

- [ ] `git diff -- golden/` is empty, **or** the regeneration is deliberate,
      justified per case, and described in the commit body.
- [ ] `impact` output is in the PR description if any pack changed.
- [ ] `SEMANTICS_VERSION` is untouched unless §4 was followed deliberately.
- [ ] The CHANGELOG entry is written (§8).
- [ ] The distribution version in `pyproject.toml` matches the tag.

## 8. The changelog entry

[CHANGELOG.md](../CHANGELOG.md) is not a commit log. Its stated job is *what
each release turned out to mean* — the boundaries that moved, the claims that
were corrected, the things that could not be done honestly. Entries are written
after the fact, from merged work.

Match the existing house style: a bold lead naming the capability, then
italic sub-paragraphs for each thing the work *taught*. The M4 entry's
"the acceptance criterion was unachievable as written" and the M5 entry's "a
bug the API tests could not see" are the model. A correction to a claim the
project previously made is worth more space than the feature that found it.

## 9. Never, as part of a release

- **Never bump `SEMANTICS_VERSION` to make the version numbers agree.** It is
  the one edit that silently invalidates 351 receipts. There is no cosmetic
  reason good enough.
- **Never regenerate `golden/` to make `verify` pass.** Regeneration is a
  reviewed baseline change with a justification per flipped case, never a way
  to clear a red check.
- **Never hand-edit a case or receipt.** Change the generator or the pack and
  regenerate; re-run the arc through the queue for `review-*` cases.
- **Never edit a committed ontology version file.** New terms, new version.
- **Never change a released pack version in place.** Replay depends on the
  repository's immutability discipline, not on a hash of the pack bytes.
- **Never commit to `main`.** Branch, PR, squash-merge — including for
  releases.

## See also

- [CLAUDE.md](../CLAUDE.md) — the `engine` block gotcha, stated for agents
- [golden/README.md](../golden/README.md) — corpus contract and regeneration rules
- [rulepacks/README.md](../rulepacks/README.md) — pack authoring and what is not auto-wired
- [ontologies/README.md](../ontologies/README.md) — the immutability rule
- [CHANGELOG.md](../CHANGELOG.md) — what each release turned out to mean
