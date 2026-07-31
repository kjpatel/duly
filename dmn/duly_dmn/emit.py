"""Pack dict -> pack.yaml text, byte-deterministically and in house style.

Why not `yaml.dump`: a compiled pack is meant to be *read* in review beside
hand-written packs, and PyYAML cannot emit the provenance header a generated
file must carry, cannot keep `given` bindings on one line the way the authored
packs do, and offers no byte-stability guarantee across its own versions.
Byte-stability is the contract here, not a nicety.

The emitter is small because the value space is small: strings, integers,
booleans, lists, and mappings, no more. `dmn/tests/test_determinism.py`
round-trips every emitted document through `yaml.safe_load` and asserts it
reconstructs the input dict exactly, so a quoting bug is a test failure and
not a silently different pack.

Key order is insertion order, everywhere. Nothing is sorted at emit time: the
compiler already fixed the order (document order of the DMN), and re-sorting
here would hide an ordering bug upstream instead of exposing it.
"""

from __future__ import annotations

import re

# Plain (unquoted) scalars are restricted to single-token identifiers, CURIEs
# and slash-separated names — the shapes that can never be mistaken for a
# number, a date, or a boolean. Everything else is quoted. The restriction is
# deliberately tighter than YAML requires: `0.00` becoming a float and
# `2015-10-03` becoming a date object are exactly the bugs this file must not
# have, and a rule that only permits what is obviously a name cannot have them.
_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_./-]*(?::[A-Za-z0-9_./-]+)*$")
_RESERVED_PLAIN = frozenset(
    {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "~"}
)

# Mappings that read better inline, matching the hand-written packs.
_FLOW_KEYS = frozenset({"citation", "value"})
# Keys whose *child* mappings render inline: `fee: { entityType: trid:Fee }`.
_FLOW_CHILDREN_OF = frozenset({"given"})
_FLOW_MAX_LEN = 84

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def _dmn_header(source: str | None) -> list[str]:
    lines = ["# Compiled from DMN by `python -m duly_dmn compile` — do not hand-edit."]
    if source:
        lines.append(f"# Source: {source}")
    lines += [
        "# The DMN decision table is the authored artifact; this file is its",
        "# compilation into the rule IR (spec/rule-ir.md, spec/dmn.md).",
    ]
    return lines


def emit_pack(
    pack: dict, *, source: str | None = None, header: list[str] | None = None
) -> str:
    """Render a rule-IR pack dict as YAML text. Ends with a newline.

    `header` replaces the DMN provenance comment for callers that are not the
    DMN compiler. It is a parameter rather than a second emitter because the
    byte-stability contract belongs to the *body*, and forking the body
    renderer to change four comment lines is how two renderers drift apart.
    A generated pack must always say how it was generated, so the header is
    replaceable but not removable.
    """
    lines = list(header) if header is not None else _dmn_header(source)
    if header is not None and source:
        lines.append(f"# Source: {source}")
    lines.append("")
    # Every top-level key, in the input dict's own order. Emitting a fixed
    # allow-list was a silent-truncation bug waiting to happen: the compiler
    # only ever produces pack/decisions/rules, but a hand-written pack also
    # carries `abstentionPolicy` and `calendars`, and dropping either would
    # re-emit a pack that adjudicates differently while looking fine.
    for key, value in pack.items():
        lines.extend(_block_entry(key, value, 0, flow_child=False))
        lines.append("")
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _block_entry(key: str, value, indent: int, *, flow_child: bool) -> list[str]:
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [f"{pad}{_key(key)}: {{}}"]
        if key in _FLOW_KEYS or flow_child:
            flow = _try_flow(value)
            if flow is not None:
                return [f"{pad}{_key(key)}: {flow}"]
        out = [f"{pad}{_key(key)}:"]
        children_flow = key in _FLOW_CHILDREN_OF
        for k, v in value.items():
            out.extend(_block_entry(k, v, indent + 1, flow_child=children_flow))
        return out
    if isinstance(value, list):
        if not value:
            return [f"{pad}{_key(key)}: []"]
        inline = _try_flow_list(value)
        if inline is not None:
            return [f"{pad}{_key(key)}: {inline}"]
        out = [f"{pad}{_key(key)}:"]
        for item in value:
            out.extend(_list_item(item, indent + 1))
        return out
    return [f"{pad}{_key(key)}: {_scalar(value)}"]


def _list_item(item, indent: int) -> list[str]:
    pad = "  " * indent
    if isinstance(item, dict):
        rendered: list[str] = []
        for k, v in item.items():
            rendered.extend(_block_entry(k, v, indent + 1, flow_child=False))
        # Splice the dash onto the first physical line of the mapping.
        rendered[0] = f"{pad}- {rendered[0][len(pad) + 2:]}"
        return rendered
    return [f"{pad}- {_scalar(item)}"]


def _try_flow(value: dict) -> str | None:
    if any(isinstance(v, (dict, list)) for v in value.values()):
        return None
    body = ", ".join(f"{_key(k)}: {_scalar(v)}" for k, v in value.items())
    rendered = "{ " + body + " }"
    return rendered if len(rendered) <= _FLOW_MAX_LEN else None


def _try_flow_list(value: list) -> str | None:
    """Only lists of plain scalars go inline. A `when` item is a quoted
    expression, so conditions always land as a readable block list."""
    if any(isinstance(v, (dict, list)) for v in value):
        return None
    if not all(_is_plain(str(v)) for v in value):
        return None
    rendered = "[" + ", ".join(_scalar(v) for v in value) + "]"
    return rendered if len(rendered) <= _FLOW_MAX_LEN else None


def _is_plain(text: str) -> bool:
    return bool(_PLAIN.match(text)) and text.lower() not in _RESERVED_PLAIN


def _key(key: str) -> str:
    return key if _is_plain(key) else _quote(key)


def _scalar(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        # Confidence floors are the only floats a pack carries, and they must
        # come back as floats: quoted, `minConfidence: "0.9"` is a string the
        # kernel rejects. `repr` is the shortest representation that round-trips
        # exactly, and it is deterministic across runs and platforms.
        if value != value:
            return ".nan"
        if value in (float("inf"), float("-inf")):
            return ".inf" if value > 0 else "-.inf"
        # ...but repr round-trips through *Python*, and this text is read back
        # by PyYAML, whose YAML-1.1 float pattern requires a decimal point in
        # the mantissa. `repr(1e-05)` is "1e-05", which reloads as the string
        # "1e-05" — the very failure quoting would cause. So the exponent form
        # gets its point back.
        mantissa, marker, exponent = repr(value).partition("e")
        if marker and "." not in mantissa:
            mantissa += ".0"
        return mantissa + marker + exponent
    text = str(value)
    return text if _is_plain(text) else _quote(text)


def _quote(text: str) -> str:
    # Single quotes when the text carries double quotes of its own and no
    # apostrophe: `'feeType == "TransferTax"'` reads like the cell it came from,
    # where the double-quoted form would bury it in backslashes.
    if '"' in text and "'" not in text and not any(c in text for c in "\n\r\t\\"):
        return f"'{text}'"
    body = "".join(_ESCAPES.get(ch, ch) for ch in text)
    return f'"{body}"'
