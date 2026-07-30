"""Every committed refusal example, compiled, with its error inspected.

A compiler's refusals are half its contract: the half that decides whether an
author can fix their table without reading the compiler's source. So these
tests assert on the *content* of the message — the row, the rule id, the
offending text — not merely that something was raised.
"""

from __future__ import annotations

import pytest

from duly_dmn import compile_file
from duly_dmn.errors import DmnCompileError
from dmntest_helpers import REFUSALS

# file -> (refusal class, fragments the message must contain)
CASES = {
    "non-sfeel-cell.dmn": (
        "unsupported-expression",
        ["function 'sum'", "row 1", "REFUSE-SFEEL-01", "column 'actual'", "sum(disclosed, 100)"],
    ),
    "unsupported-hit-policy.dmn": (
        "unsupported-hit-policy",
        ["COLLECT", "list", "UNIQUE, FIRST, PRIORITY", "decision 'category'"],
    ),
    "uncited-row.dmn": (
        "missing-citation",
        ["duly:citation", "row 2", "REFUSE-CITE-02", "TODO(verify)"],
    ),
    "undated-row.dmn": (
        "missing-effective-date",
        ["duly:effectiveFrom", "row 1", "REFUSE-DATE-01", "effective-dated"],
    ),
    "unprovable-unique.dmn": (
        "unprovable-unique",
        ["UNIQUE", "rows 1 and 2", "REFUSE-UNIQ-01", "REFUSE-UNIQ-02", "FIRST"],
    ),
    "multiple-outputs.dmn": (
        "unsupported-table-shape",
        ["2 output columns", "one attribute", "decision 'category'"],
    ),
}


@pytest.mark.parametrize("filename", sorted(CASES))
def test_refusal_example_fails_with_the_right_class_and_message(filename):
    klass, fragments = CASES[filename]
    with pytest.raises(DmnCompileError) as excinfo:
        compile_file(REFUSALS / filename)
    assert excinfo.value.klass == klass
    message = str(excinfo.value)
    for fragment in fragments:
        assert fragment in message, f"{filename}: message does not mention {fragment!r}"


def test_every_committed_refusal_example_is_covered():
    """A refusal example added without a test is a refusal nobody checked."""
    on_disk = {p.name for p in REFUSALS.glob("*.dmn")}
    assert on_disk == set(CASES)


def test_the_refusal_readme_lists_every_example():
    readme = (REFUSALS / "README.md").read_text(encoding="utf-8")
    for filename in CASES:
        assert filename in readme


def test_no_refusal_example_compiles_by_accident():
    """Guards against an example that stops being broken — e.g. after a
    compiler change makes its defect legal."""
    for filename in CASES:
        with pytest.raises(DmnCompileError):
            compile_file(REFUSALS / filename)
