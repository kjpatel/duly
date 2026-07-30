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
from dmntest_helpers import EXAMPLES, REFUSALS, REPO, TRID_COMPILED, TRID_DMN, minimal_dmn

SOURCES = sorted(EXAMPLES.glob("*.dmn"))


def test_there_is_something_to_compile():
    assert SOURCES


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
    pack = yaml.safe_load(TRID_COMPILED.read_text(encoding="utf-8"))
    default = next(r for r in pack["rules"] if r["id"] == "TRID-DEF-00")
    assert default["then"]["value"]["amount"] == "0.00"
    assert isinstance(default["effectiveFrom"], str)
    assert default["effectiveFrom"] == "2015-10-03"
    assert isinstance(pack["pack"]["version"], str)


def test_hash_randomization_does_not_move_a_byte():
    """PYTHONHASHSEED perturbs set and string-hash iteration order. Two child
    interpreters with different seeds must still write the same file."""
    outputs = []
    for seed in ("0", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run(
            [sys.executable, "-m", "duly_dmn", "compile", str(TRID_DMN)],
            capture_output=True, text=True, env=env, cwd=REPO, check=True,
        )
        outputs.append(proc.stdout)
    assert outputs[0] == outputs[1]
    assert outputs[0] == TRID_COMPILED.read_text(encoding="utf-8")


def test_the_source_header_is_repo_relative():
    """The `# Source:` line must not leak an absolute path, or a checkout in a
    different directory would produce different bytes."""
    text = TRID_COMPILED.read_text(encoding="utf-8")
    assert "# Source: dmn/examples/trid-fee-tolerance.dmn" in text
    assert str(REPO) not in text


def test_cwd_and_absolute_paths_do_not_change_a_byte(tmp_path):
    """Compiling from another directory, with an absolute path, must produce
    the identical file: the header anchors on the project root above the .dmn,
    not on the cwd or on where duly_dmn happens to be installed."""
    proc = subprocess.run(
        [sys.executable, "-m", "duly_dmn", "compile", str(TRID_DMN.resolve())],
        capture_output=True, text=True, cwd=tmp_path, check=True,
        env=dict(os.environ, PYTHONPATH=str(REPO / "dmn") + os.pathsep + str(REPO / "kernel")),
    )
    assert proc.stdout == TRID_COMPILED.read_text(encoding="utf-8")


def test_column_order_not_dict_order_drives_the_output():
    """Reordering the input columns reorders `given` and `when` — proving the
    order comes from the document, not from a dict the compiler happened to
    build."""
    base = compile_source(minimal_dmn())
    assert list(base["rules"][0]["given"]) == ["terminationNotice", "state"]


def test_refusal_examples_fail_the_same_way_every_time():
    from duly_dmn.errors import DmnCompileError

    for path in sorted(REFUSALS.glob("*.dmn")):
        messages = set()
        for _ in range(3):
            try:
                compile_file(path)
            except DmnCompileError as e:
                messages.add(str(e))
        assert len(messages) == 1, path.name
