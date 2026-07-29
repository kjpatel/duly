import json

import pytest

from duly_kernel.__main__ import main

from conftest import FIXTURES, REPO_ROOT, SPEC_EXAMPLES


def run_cli(capsys, *extra: str) -> dict:
    argv = [
        "--facts", str(SPEC_EXAMPLES),
        "--pack", str(FIXTURES / "ny-pack.yaml"),
        "--asof", "2026-07-25",
        "--question", "nc:noticeCompliant",
        *extra,
    ]
    assert main(argv) == 0
    out = capsys.readouterr().out
    return json.loads(out)


def test_cli_prints_receipt(capsys):
    receipt = run_cli(capsys)
    assert receipt["decision"]["value"] == {"kind": "boolean", "value": False}
    assert receipt["asOf"]["effective"] == "2026-07-25T00:00:00Z"
    # No wall-clock defaulting: knowledge defaults to the asOf date's end.
    assert receipt["asOf"]["knowledge"] == "2026-07-25T23:59:59Z"


def test_cli_explicit_knowledge(capsys):
    receipt = run_cli(capsys, "--asof-knowledge", "2026-07-30T16:00:00Z")
    assert receipt["asOf"]["knowledge"] == "2026-07-30T16:00:00Z"


def test_cli_receipt_validates_against_schema(capsys):
    jsonschema = pytest.importorskip("jsonschema")
    from referencing import Registry, Resource

    receipt = run_cli(capsys, "--asof-knowledge", "2026-07-30T16:00:00Z")

    schemas_dir = REPO_ROOT / "spec" / "schemas"
    registry = Registry()
    schemas = {}
    for path in sorted(schemas_dir.glob("*.schema.json")):
        schema = json.loads(path.read_text(encoding="utf-8"))
        schemas[schema["title"]] = schema
        registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))

    validator = jsonschema.Draft202012Validator(
        schemas["DecisionReceipt"], registry=registry,
        format_checker=jsonschema.FormatChecker(),
    )
    errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in validator.iter_errors(receipt)]
    assert errors == []
