"""Interpreter for the constrained LinkML subset duly consumes.

The committed ontology files under ``ontologies/`` are genuine LinkML —
loadable by linkml-runtime, compilable to SHACL (proven by the
marker-gated tests in conformance/tests/test_real_linkml.py). This module
is NOT a LinkML implementation; it reads exactly the subset the
conformance gate enforces and treats everything else as documentation.

Interpreted (spec/ontology-conformance.md, "The subset"):

- ``name`` / ``version`` — the identity a fact's ``schemaRef`` pins.
- ``prefixes`` — CURIE prefixes; a fact term with an undeclared prefix is
  nonconformant.
- ``classes.*.class_uri`` — the entity-type CURIE a class defines.
- ``classes.*.attributes.*.slot_uri`` — the attribute CURIE a slot
  defines, scoped to its class.
- ``attributes.*.range`` — mapped to a duly value kind: the built-in
  LinkML types string/decimal/date/datetime/boolean map to the value
  kinds of the same name; a schema-local type whose ``uri`` is
  ``duly:money`` (or ``duly:entityRef``) maps to that kind; an enum range
  maps to ``code``.
- ``attributes.*.required`` — parsed and carried, but NOT enforced by the
  fact gate: facts are atomic (grounded-facts D1), so no single fact can
  witness a missing sibling attribute. Completeness is adjudication's
  job — a missing attribute surfaces as an abstention on the receipt.
- ``enums`` — ``permissible_values`` (closed membership),
  ``annotations.codeSystem`` (the code-system string a fact's code value
  must carry), ``annotations.openCodeSet`` (external standard: identity
  checked, membership not vendored).

Ignored as documentation, deliberately: descriptions, comments,
``close_mappings``/``exact_mappings``, ``annotations.mismo``,
``annotations.derived``, ``code_set``, ``license``, ``imports``,
``default_range``, and any other LinkML feature. An attribute whose range
names something outside the subset is a LOAD-TIME error, not a silent
skip — the gate refuses to enforce an ontology it cannot fully interpret.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["OntologySubsetError", "SlotDef", "ClassDef", "EnumDef", "Ontology", "parse_ontology"]

# LinkML built-in ranges that map 1:1 onto duly value kinds. Anything else
# must be a schema-local enum or a schema-local type with a duly:* uri.
_BUILTIN_RANGE_KINDS = {
    "string": "string",
    "decimal": "decimal",
    "date": "date",
    "datetime": "datetime",
    "boolean": "boolean",
}

# Schema-local type uris that name a duly value kind.
_TYPE_URI_KINDS = {
    "duly:money": "money",
    "duly:entityRef": "entityRef",
}


class OntologySubsetError(Exception):
    """The ontology document steps outside the enforceable subset."""


@dataclass(frozen=True)
class EnumDef:
    name: str
    code_system: str | None
    open_code_set: bool
    values: frozenset[str]


@dataclass(frozen=True)
class SlotDef:
    name: str
    curie: str
    kind: str
    required: bool
    enum: EnumDef | None = None


@dataclass(frozen=True)
class ClassDef:
    name: str
    curie: str
    slots: dict[str, SlotDef] = field(default_factory=dict)  # keyed by slot CURIE


@dataclass(frozen=True)
class Ontology:
    name: str
    version: str
    prefixes: dict[str, str]
    classes: dict[str, ClassDef] = field(default_factory=dict)  # keyed by class CURIE

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def find_slot(self, attribute: str) -> tuple[ClassDef, SlotDef] | None:
        """The (class, slot) defining ``attribute``, wherever it lives."""
        for cls in self.classes.values():
            slot = cls.slots.get(attribute)
            if slot is not None:
                return cls, slot
        return None


def _annotation(node: dict, tag: str):
    """An annotation value, tolerating both LinkML shorthand
    (``annotations: {tag: value}``) and expanded
    (``annotations: {tag: {tag: ..., value: ...}}``) forms."""
    raw = (node.get("annotations") or {}).get(tag)
    if isinstance(raw, dict):
        return raw.get("value")
    return raw


def _prefix_of(curie: str) -> str:
    if ":" not in curie:
        raise OntologySubsetError(f"{curie!r} is not a CURIE (no prefix)")
    return curie.split(":", 1)[0]


def parse_ontology(doc: dict) -> Ontology:
    """Parse one LinkML schema document into the enforceable subset.

    Raises OntologySubsetError when the document is missing something the
    gate needs (name, version, class_uri/slot_uri, a resolvable range) —
    loudly at load time, never silently at check time.
    """
    name = doc.get("name")
    version = doc.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise OntologySubsetError("ontology document needs string `name` and `version`")
    prefixes = doc.get("prefixes") or {}
    if not isinstance(prefixes, dict) or not prefixes:
        raise OntologySubsetError(f"{name}@{version}: no `prefixes` declared")

    types_by_name: dict[str, str] = {}  # local type name -> duly kind
    for type_name, type_def in (doc.get("types") or {}).items():
        uri = (type_def or {}).get("uri")
        kind = _TYPE_URI_KINDS.get(uri)
        if kind is None:
            raise OntologySubsetError(
                f"{name}@{version}: type {type_name!r} has uri {uri!r}, which names "
                f"no duly value kind (expected one of {sorted(_TYPE_URI_KINDS)})"
            )
        types_by_name[type_name] = kind

    enums_by_name: dict[str, EnumDef] = {}
    for enum_name, enum_def in (doc.get("enums") or {}).items():
        enum_def = enum_def or {}
        code_system = _annotation(enum_def, "codeSystem")
        open_code_set = bool(_annotation(enum_def, "openCodeSet"))
        values = frozenset((enum_def.get("permissible_values") or {}).keys())
        if not open_code_set and not values:
            raise OntologySubsetError(
                f"{name}@{version}: enum {enum_name!r} has no permissible_values and "
                "is not marked openCodeSet — the gate could never accept a value"
            )
        enums_by_name[enum_name] = EnumDef(
            name=enum_name,
            code_system=code_system if isinstance(code_system, str) else None,
            open_code_set=open_code_set,
            values=values,
        )

    classes: dict[str, ClassDef] = {}
    for class_name, class_def in (doc.get("classes") or {}).items():
        class_def = class_def or {}
        class_curie = class_def.get("class_uri")
        if not isinstance(class_curie, str):
            raise OntologySubsetError(
                f"{name}@{version}: class {class_name!r} has no class_uri — the gate "
                "matches entity types by CURIE, so every class must declare one"
            )
        if _prefix_of(class_curie) not in prefixes:
            raise OntologySubsetError(
                f"{name}@{version}: class_uri {class_curie!r} uses an undeclared prefix"
            )
        slots: dict[str, SlotDef] = {}
        for slot_name, slot_def in (class_def.get("attributes") or {}).items():
            slot_def = slot_def or {}
            slot_curie = slot_def.get("slot_uri")
            if not isinstance(slot_curie, str):
                raise OntologySubsetError(
                    f"{name}@{version}: attribute {class_name}.{slot_name} has no "
                    "slot_uri — the gate matches attributes by CURIE"
                )
            if _prefix_of(slot_curie) not in prefixes:
                raise OntologySubsetError(
                    f"{name}@{version}: slot_uri {slot_curie!r} uses an undeclared prefix"
                )
            range_name = slot_def.get("range")
            enum = None
            if range_name in _BUILTIN_RANGE_KINDS:
                kind = _BUILTIN_RANGE_KINDS[range_name]
            elif range_name in types_by_name:
                kind = types_by_name[range_name]
            elif range_name in enums_by_name:
                kind = "code"
                enum = enums_by_name[range_name]
            else:
                raise OntologySubsetError(
                    f"{name}@{version}: attribute {slot_curie} has range {range_name!r}, "
                    "which is neither a supported built-in (string/decimal/date/"
                    "datetime/boolean) nor a schema-local type or enum"
                )
            slots[slot_curie] = SlotDef(
                name=slot_name,
                curie=slot_curie,
                kind=kind,
                required=bool(slot_def.get("required", False)),
                enum=enum,
            )
        classes[class_curie] = ClassDef(name=class_name, curie=class_curie, slots=slots)

    if not classes:
        raise OntologySubsetError(f"{name}@{version}: no classes declared")
    return Ontology(name=name, version=version, prefixes=dict(prefixes), classes=classes)
