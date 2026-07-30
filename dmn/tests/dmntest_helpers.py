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
