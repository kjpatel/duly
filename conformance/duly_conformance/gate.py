"""The conformance checks themselves (spec/ontology-conformance.md, C5).

``check_fact`` returns every issue found (not just the first), each naming
the fact, the ontology reference, and what failed — the loud, attributable
rejection the gate exists to produce. What it checks:

1. the referenced ontology + version exists in the registry (exact pin);
2. the entity type CURIE is a class the ontology defines;
3. the attribute CURIE is a slot declared on that class (a slot that
   exists on a different class is called out as misattachment);
4. the value's ``kind`` matches the slot's declared range;
5. a code value's ``codeSystem`` matches the enum's declared code system,
   and — for closed enums — the value is a permissible value.

Deliberately NOT checked here: spans and hashes (the envelope owns run
integrity), required-ness (facts are atomic; completeness surfaces as
adjudication abstention), and ``codeSystemVersion`` (code-system
versioning policy belongs to the code system, not the gate — see the
spec's honest boundaries).
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from .registry import OntologyRegistry

__all__ = ["ConformanceIssue", "FactNonconformantError", "check_fact", "assert_conformant"]


@dataclass(frozen=True)
class ConformanceIssue:
    fact_id: str
    ontology_ref: str
    code: str  # unknown_ontology | unknown_entity_type | unknown_attribute | misattached_attribute | kind_mismatch | code_system_mismatch | code_not_permitted
    message: str

    def __str__(self) -> str:
        return f"{self.fact_id}: [{self.code}] {self.message}"


class FactNonconformantError(Exception):
    """Raised by assert_conformant; carries every issue found."""

    def __init__(self, issues: list[ConformanceIssue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues))


def _suggest(name: str, candidates: list[str]) -> str:
    close = difflib.get_close_matches(name, candidates, n=1)
    return f" (did you mean {close[0]!r}?)" if close else ""


def check_fact(fact: dict, registry: OntologyRegistry) -> list[ConformanceIssue]:
    """Every conformance issue in ``fact``, resolved against ``registry``."""
    fact_id = str(fact.get("id", "<no id>"))
    schema_ref = fact.get("schemaRef") or {}
    name = schema_ref.get("ontology")
    version = schema_ref.get("version")
    ref = f"{name}@{version}"

    ontology = registry.get(name, version) if name and version else None
    if ontology is None:
        return [
            ConformanceIssue(
                fact_id,
                ref,
                "unknown_ontology",
                f"schemaRef pins {ref}, which is not in the registry "
                f"(known: {', '.join(registry.refs()) or 'none'}); version pinning "
                "is exact — no fallback across versions",
            )
        ]

    issues: list[ConformanceIssue] = []
    entity_type = (fact.get("entity") or {}).get("type")
    attribute = fact.get("attribute")

    cls = ontology.classes.get(entity_type)
    if cls is None:
        issues.append(
            ConformanceIssue(
                fact_id,
                ref,
                "unknown_entity_type",
                f"entity type {entity_type!r} is not a class {ref} defines"
                f"{_suggest(str(entity_type), list(ontology.classes))}",
            )
        )

    slot = cls.slots.get(attribute) if cls is not None else None
    if slot is None:
        elsewhere = ontology.find_slot(attribute)
        if cls is not None and elsewhere is not None:
            other_cls, _ = elsewhere
            issues.append(
                ConformanceIssue(
                    fact_id,
                    ref,
                    "misattached_attribute",
                    f"attribute {attribute!r} is declared on {other_cls.curie}, "
                    f"not on {cls.curie}",
                )
            )
        else:
            all_slots = [s for c in ontology.classes.values() for s in c.slots]
            issues.append(
                ConformanceIssue(
                    fact_id,
                    ref,
                    "unknown_attribute",
                    f"attribute {attribute!r} is not declared anywhere in {ref}"
                    f"{_suggest(str(attribute), all_slots)}",
                )
            )
        return issues  # value checks need a slot to check against

    value = fact.get("value") or {}
    kind = value.get("kind")
    if kind != slot.kind:
        issues.append(
            ConformanceIssue(
                fact_id,
                ref,
                "kind_mismatch",
                f"attribute {attribute!r} is declared {slot.kind} in {ref}, "
                f"but the value's kind is {kind!r}",
            )
        )
        return issues

    if slot.enum is not None:
        code = value.get("value")
        code_system = value.get("codeSystem")
        if slot.enum.code_system is not None and code_system != slot.enum.code_system:
            issues.append(
                ConformanceIssue(
                    fact_id,
                    ref,
                    "code_system_mismatch",
                    f"attribute {attribute!r} expects codeSystem "
                    f"{slot.enum.code_system!r}, got {code_system!r}",
                )
            )
        if not slot.enum.open_code_set and code not in slot.enum.values:
            issues.append(
                ConformanceIssue(
                    fact_id,
                    ref,
                    "code_not_permitted",
                    f"code {code!r} is not a permissible value of "
                    f"{slot.enum.name} in {ref} "
                    f"(permitted: {', '.join(sorted(slot.enum.values))})"
                    f"{_suggest(str(code), sorted(slot.enum.values))}",
                )
            )
    return issues


def assert_conformant(fact: dict, registry: OntologyRegistry) -> None:
    """Raise FactNonconformantError if ``fact`` has any issue."""
    issues = check_fact(fact, registry)
    if issues:
        raise FactNonconformantError(issues)
