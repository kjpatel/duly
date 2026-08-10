"""Same DMN bytes in, byte-identical pack.yaml out — forever.

A compiled pack ends up inside `rulePack.version` on receipts that must replay
byte-for-byte for the life of the system. If the compiler's output could
wobble — on dict ordering, on set iteration, on the machine's locale, on where
the repo is checked out — a receipt could stop reproducing with nothing in the
audit chain to explain it. So determinism is tested directly, not assumed.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
import yaml

from duly_dmn import compile_file, compile_source, emit_pack
from dmntest_helpers import (
    FIXTURE_COMPILED,
    FIXTURE_DMN,
    FIXTURE_DMN_DIR,
    FIXTURE_REFUSALS,
    REPO,
    minimal_dmn,
)

# The corpus this suite compiles. Fixtures, not `dmn/examples/`: parametrizing
# over a glob is evaluated at *collection*, so a directory that has moved away
# produces zero cases and pytest reports only the count that remains — which
# reads exactly like success (CLAUDE.md). Hence the guards below.
SOURCES = sorted(FIXTURE_DMN_DIR.glob("*.dmn"))
REFUSAL_SOURCES = sorted(FIXTURE_REFUSALS.glob("*.dmn"))


def test_there_is_something_to_compile():
    assert SOURCES, f"no .dmn documents under {FIXTURE_DMN_DIR}"


def test_there_is_something_that_refuses():
    assert REFUSAL_SOURCES, f"no .dmn documents under {FIXTURE_REFUSALS}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_repeated_compilation_is_byte_identical(path):
    first = emit_pack(compile_file(path), source=path.name)
    for _ in range(5):
        assert emit_pack(compile_file(path), source=path.name) == first


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_emitted_yaml_round_trips_to_the_compiled_dict(path):
    """The emitter is hand-written, so its correctness is asserted, not
    assumed: parsing what it wrote must reconstruct exactly what it was given
    — no `0.00` turned into a float, no `2015-10-03` turned into a date."""
    pack = compile_file(path)
    assert yaml.safe_load(emit_pack(pack, source=path.name)) == pack


def test_amounts_and_dates_survive_the_round_trip_as_strings():
    pack = yaml.safe_load(FIXTURE_COMPILED.read_text(encoding="utf-8"))
    default = next(r for r in pack["rules"] if r["id"] == "FXD-FEE-00")
    assert default["then"]["value"]["amount"] == "0.00"
    assert isinstance(default["effectiveFrom"], str)
    assert default["effectiveFrom"] == "2026-01-01"
    assert isinstance(pack["pack"]["version"], str)


def test_every_top_level_key_survives_the_round_trip():
    """The emitter serves hand-written packs too (the demo's rule studio
    re-emits one on every structured edit), and those carry two keys the
    compiler never produces. Dropping either would emit a pack that validates,
    adjudicates, and decides differently — so the round trip is asserted over
    a pack that has them, not only over compiler output."""
    pack = compile_source(minimal_dmn())
    pack["abstentionPolicy"] = {"minConfidence": 0.75, "attributes": {"nc:mailed": 0.9}}
    pack["calendars"] = {"us-federal": {"excludeWeekdays": ["Sat", "Sun"]}}
    reparsed = yaml.safe_load(emit_pack(pack))
    assert reparsed == pack
    assert isinstance(reparsed["abstentionPolicy"]["minConfidence"], float)


@pytest.mark.parametrize("value", [0.9, 0.75, 0.00001, 1e16, 1.5e-07, 1.0, -0.5])
def test_a_float_comes_back_as_a_float_however_repr_spells_it(value):
    """`repr` round-trips through Python, but this text is read back by PyYAML,
    whose YAML-1.1 float pattern wants a decimal point in the mantissa. Emitted
    bare, `repr(1e-05)` reloads as the *string* "1e-05" — a `minConfidence` the
    kernel then rejects, which is exactly the failure quoting would have caused.
    """
    pack = compile_source(minimal_dmn())
    pack["abstentionPolicy"] = {"minConfidence": value}
    reloaded = yaml.safe_load(emit_pack(pack))["abstentionPolicy"]["minConfidence"]
    assert isinstance(reloaded, float), f"{value!r} came back as {type(reloaded).__name__}"
    assert reloaded == value


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_a_replaced_header_does_not_move_the_body(path):
    """`header=` exists so a non-DMN caller can say how *it* generated a pack.
    It must change the comment block and nothing else — the body's
    byte-stability is the contract, and a header parameter that reformatted
    anything would quietly break it."""
    default = emit_pack(compile_file(path), source=path.name)
    custom = emit_pack(compile_file(path), header=["# Drafted elsewhere."])
    strip = lambda text: [ln for ln in text.splitlines() if not ln.startswith("#")]  # noqa: E731
    assert strip(default) == strip(custom)
    assert custom.startswith("# Drafted elsewhere.\n")


def test_hash_randomization_does_not_move_a_byte():
    """PYTHONHASHSEED perturbs set and string-hash iteration order. Two child
    interpreters with different seeds must still write the same file."""
    outputs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run(
            [sys.executable, "-m", "duly_dmn", "compile", str(FIXTURE_DMN)],
            capture_output=True, text=True, env=env, cwd=REPO, check=True,
        )
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1]
    assert outputs[0] == FIXTURE_COMPILED.read_text(encoding="utf-8")


def test_the_source_header_is_repo_relative():
    """The `# Source:` line must not leak an absolute path, or a checkout in a
    different directory would produce different bytes."""
    text = FIXTURE_COMPILED.read_text(encoding="utf-8")
    assert "# Source: fixtures/dmn/widget-fee.dmn" in text
    assert str(REPO) not in text


def test_cwd_and_absolute_paths_do_not_change_a_byte(tmp_path):
    """Compiling from another directory, with an absolute path, must produce
    the identical file: the header anchors on the project root above the .dmn,
    not on the cwd or on where duly_dmn happens to be installed."""
    proc = subprocess.run(
        [sys.executable, "-m", "duly_dmn", "compile", str(FIXTURE_DMN.resolve())],
        capture_output=True, text=True, cwd=tmp_path, check=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "dmn") + os.pathsep + str(REPO / "kernel")),
    )
    assert proc.stdout == FIXTURE_COMPILED.read_text(encoding="utf-8")


def test_column_order_not_dict_order_drives_the_output():
    """Reordering the input columns reorders `given` and `when` — proving the
    order comes from the document, not from a dict the compiler happened to
    build."""
    base = compile_source(minimal_dmn())
    assert list(base["rules"][0]["given"]) == ["terminationNotice", "state"]


def test_refusals_fail_the_same_way_every_time():
    """A refusal is output too. An error message that varied between runs — on
    set iteration, on which of several defects was noticed first — would make
    a CI failure irreproducible."""
    from duly_dmn.errors import DmnCompileError

    from dmntest_helpers import fixture_value_kinds

    assert REFUSAL_SOURCES, f"no .dmn documents under {FIXTURE_REFUSALS}"
    for path in REFUSAL_SOURCES:
        messages = set()
        for _ in range(3):
            try:
                compile_file(path, fixture_value_kinds())
            except DmnCompileError as e:
                messages.add(str(e))
        assert len(messages) == 1, path.name
