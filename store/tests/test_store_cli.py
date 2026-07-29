"""CLI surface: python -m duly_store {init,ingest,query,history}."""

import json

import pytest

from duly_store.__main__ import main

from storetest_helpers import CASE_ID, SPEC_EXAMPLES, load_spec_facts


@pytest.fixture()
def spec_facts() -> list[dict]:
    return load_spec_facts()


def test_init_ingest_query_history(tmp_path, capsys, spec_facts):
    db = str(tmp_path / "facts.db")

    assert main(["init", "--db", db]) == 0
    capsys.readouterr()

    # Ingest the spec examples directory: 4 facts in, receipt skipped.
    assert main(["ingest", "--db", db, "--facts", str(SPEC_EXAMPLES)]) == 0
    out = capsys.readouterr().out
    assert "4 ingested, 0 unchanged, 0 rejected" in out
    assert "receipt-ny-nonrenewal-notice.json" not in out

    # Re-ingest is idempotent.
    assert main(["ingest", "--db", db, "--facts", str(SPEC_EXAMPLES)]) == 0
    assert "0 ingested, 4 unchanged, 0 rejected" in capsys.readouterr().out

    # Query prints the projection as JSON, ordered by fact id.
    assert main([
        "query", "--db", db, "--case", CASE_ID,
        "--knowledge", "2026-07-30T16:00:00Z", "--effective", "2026-07-25T00:00:00Z",
    ]) == 0
    projected = json.loads(capsys.readouterr().out)
    assert [f["id"] for f in projected] == sorted(f["id"] for f in spec_facts)

    # A knowledge horizon before anything was recorded projects nothing.
    assert main([
        "query", "--db", db, "--case", CASE_ID, "--knowledge", "2026-01-01",
    ]) == 0
    assert json.loads(capsys.readouterr().out) == []

    # History of a single fact.
    fact_id = spec_facts[0]["id"]
    assert main(["history", "--db", db, "--fact-id", fact_id]) == 0
    events = json.loads(capsys.readouterr().out)
    assert [e["event_kind"] for e in events] == ["asserted"]
    assert events[0]["fact_id"] == fact_id
    assert events[0]["payload"] == spec_facts[0]


def test_ingest_rejects_tampered_file(tmp_path, capsys, spec_facts):
    db = str(tmp_path / "facts.db")
    bad_dir = tmp_path / "facts"
    bad_dir.mkdir()
    tampered = dict(spec_facts[0])
    tampered["value"] = {"kind": "date", "value": "1999-01-01"}  # stale hash
    (bad_dir / "tampered.json").write_text(json.dumps(tampered), encoding="utf-8")

    assert main(["ingest", "--db", db, "--facts", str(bad_dir)]) == 1
    captured = capsys.readouterr()
    assert "0 ingested, 0 unchanged, 1 rejected" in captured.out
    assert "contentHash mismatch" in captured.err
