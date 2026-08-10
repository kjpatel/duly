"""Shared fixtures for the DMN compiler suite.

A module, not a conftest: test directories in this repo carry no
`__init__.py`, so two `conftest.py` files with the same name would collide
across suites (CLAUDE.md, "Conventions").
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

# The toolkit's own DMN corpus: what this suite compiles when it is asserting
# *compiler* behaviour. Sized to the two hit policies that compile differently
# and to one refusal; see fixtures/README.md.
FIXTURES = REPO / "fixtures"
FIXTURE_DMN_DIR = FIXTURES / "dmn"
FIXTURE_DMN = FIXTURE_DMN_DIR / "widget-fee.dmn"
FIXTURE_COMPILED = FIXTURE_DMN_DIR / "widget-fee.pack.yaml"
FIXTURE_REFUSALS = FIXTURE_DMN_DIR / "refusals"
FIXTURE_ONTOLOGIES = FIXTURES / "ontology"

# EXAMPLE CONTENT (moves with `examples/`). Teaching content: the TRID table is
# the one an adopter reads and then deletes. Only the two suites whose *subject*
# is that content may reach for these — `test_equivalence.py` (does the compiled
# pack decide what the hand-written one decides?) and `test_refusals.py` (does
# every committed refusal example refuse?). A test about the compiler belongs on
# the fixture constants above, or a `git rm -r dmn/examples/` leaves it passing
# over an empty glob (CLAUDE.md).
EXAMPLES = REPO / "dmn" / "examples"
REFUSALS = EXAMPLES / "refusals"

TRID_DMN = EXAMPLES / "trid-fee-tolerance.dmn"
TRID_COMPILED = EXAMPLES / "trid-fee-tolerance.pack.yaml"
TRID_HAND_WRITTEN = REPO / "rulepacks" / "trid-fee-tolerance-us-federal" / "pack.yaml"
TRID_EXPECTED = REPO / "rulepacks" / "trid-fee-tolerance-us-federal" / "expected.yaml"
TRID_FACTS = REPO / "starters" / "trid" / "facts"


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_facts(directory: Path) -> list[dict]:
    facts = []
    for path in sorted(directory.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        if "receiptSha256" in doc:
            continue
        facts.append(doc)
    return facts


# A one-decision, one-row table with every required annotation filled in.
# Tests mutate the placeholders to isolate a single defect at a time, which
# keeps a failure message about the thing the test is named after.
MINIMAL_DMN = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="{ns}" xmlns:duly="urn:duly:dmn:0.1"
             id="t" name="t" namespace="urn:duly:test">
  <extensionElements>
    <duly:pack name="test-pack" version="0.0.1"/>
  </extensionElements>
  <decision id="d" name="nc:noticeCompliant">
    <question>Was this termination notice compliant?</question>
    <extensionElements>
      <duly:decision entityType="nc:TerminationNotice" attribute="nc:noticeCompliant"
                     valueKind="boolean" {extra}/>
    </extensionElements>
    <decisionTable id="dt" hitPolicy="{hit_policy}">
      <input id="i1" label="state">
        <inputExpression typeRef="string"><text>nc:governingState</text></inputExpression>
      </input>
      <output id="o1" label="compliant" typeRef="boolean"/>
      <annotation name="duly:ruleId"/>
      <annotation name="duly:citation"/>
      <annotation name="duly:effectiveFrom"/>
      <rule id="r1">
        <inputEntry><text>{cell}</text></inputEntry>
        <outputEntry><text>{output}</text></outputEntry>
        <annotationEntry><text>{rule_id}</text></annotationEntry>
        <annotationEntry><text>{citation}</text></annotationEntry>
        <annotationEntry><text>{effective_from}</text></annotationEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
"""

DMN_13 = "https://www.omg.org/spec/DMN/20191111/MODEL/"


def minimal_dmn(**overrides: str) -> str:
    """Render MINIMAL_DMN, overriding any placeholder."""
    values = {
        "ns": DMN_13,
        "hit_policy": "UNIQUE",
        "cell": '"US-NY"',
        "output": "true",
        "rule_id": "T-01",
        "citation": "N.Y. Ins. Law &#167; 3425(d)(1)",
        "effective_from": "1986-01-01",
        "extra": "",
    }
    values.update(overrides)
    return MINIMAL_DMN.format(**values)


def value_kinds(ontologies: Path) -> dict[str, str]:
    """Attribute CURIE -> duly value kind, from a directory of ontologies.

    The compiler takes this mapping rather than a path, so it never reaches
    for a directory of its own choosing. Tests and the spec demo are
    repo-resident and may supply a repo directory; a compiler that did the
    same would be assuming a layout it cannot rely on.

    It exists because of the one defect DMN cannot self-diagnose: a money
    column tested against a bare number. DMN's `typeRef` is the author's
    declaration and duly's value kinds are not DMN's.
    """
    from duly_conformance import load_repo_registry

    kinds: dict[str, str] = {}
    for ontology in load_repo_registry(ontologies):
        for klass in ontology.classes.values():
            for slot in klass.slots.values():
                kinds[slot.curie] = slot.kind
    return kinds


def fixture_value_kinds() -> dict[str, str]:
    """The mapping for the fixture DMN's vocabulary (`fixtures/ontology/`)."""
    return value_kinds(FIXTURE_ONTOLOGIES)


def refusal_value_kinds() -> dict[str, str]:
    """EXAMPLE CONTENT (moves with `examples/`): the mapping the committed
    refusal *examples* pin, from this repository's own `ontologies/`."""
    return value_kinds(REPO / "ontologies")
