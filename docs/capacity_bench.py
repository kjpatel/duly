#!/usr/bin/env python3
"""The measurement harness behind docs/capacity-envelope.md.

Times duly's reference kernel **from outside it**. No wall clock ever enters
library code (CLAUDE.md invariant), so every number here is produced by a
caller that the kernel cannot see. Nothing this script measures is written to
a receipt, a golden file, or any other replayable artifact: timings are not
deterministic and do not belong in one. They belong in a document, with the
machine and the date attached.

    uv run python docs/capacity_bench.py                 # everything
    uv run python docs/capacity_bench.py --only corpus   # one section
    uv run python docs/capacity_bench.py --json out.json # machine-readable

Sections:
  corpus   per-case adjudication latency over the committed golden corpus,
           by pack, with pack parse / IR validation / evaluation separated
  replay   `duly-verify` over the whole corpus, end to end, in a subprocess
  memory   tracemalloc peak for one adjudication; RSS floor of a whole process
  scaling  synthetic packs of growing rule count and cases of growing fact
           count, built in memory from the fixture pack's shape and committed
           nowhere

`corpus` and `replay` need the teaching content under `examples/`; `memory`
and `scaling` run on `fixtures/` and survive its deletion. A missing section
says so and the rest still runs.
"""

from __future__ import annotations

import argparse
import copy
import json
import platform
import resource
import subprocess
import sys
import time
import tracemalloc
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from duly_kernel.api import adjudicate  # noqa: E402
from duly_kernel.engine import evaluate_pack, normalize_point  # noqa: E402
from duly_kernel.ir import validate_pack  # noqa: E402
from duly_kernel.receipt import build_receipt  # noqa: E402

GOLDEN = REPO / "examples" / "golden"
RULEPACKS = REPO / "examples" / "rulepacks"
FIXTURE_PACK = REPO / "fixtures" / "pack.yaml"
FIXTURE_CASE = REPO / "fixtures" / "cases" / "fx-0001"

# Every timing is the best of REPEATS runs of the same input. The minimum is
# the estimator here, not the mean: the quantity being measured is the cost of
# the work, and everything the OS adds to a sample is additive noise. The
# spread across the corpus's own cases is then a real distribution over inputs
# rather than a distribution over scheduler luck.
REPEATS = 7


# --------------------------------------------------------------------------
# timing helpers


def best(fn, repeats: int = REPEATS) -> float:
    """Seconds: the fastest of `repeats` calls."""
    out = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        out = min(out, time.perf_counter() - t0)
    return out


def pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile. Small n is the caller's problem to disclose."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100.0 * len(ordered) + 0.5)) - 1))
    return ordered[k]


def ms(x: float) -> str:
    return f"{x * 1000:.3f}"


def summarize(values: list[float]) -> dict:
    return {
        "n": len(values),
        "p50_ms": pct(values, 50) * 1000,
        "p95_ms": pct(values, 95) * 1000,
        "p99_ms": pct(values, 99) * 1000,
        "max_ms": (max(values) if values else float("nan")) * 1000,
        "min_ms": (min(values) if values else float("nan")) * 1000,
    }


def table(rows: list[list[str]], headers: list[str]) -> str:
    widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]
    line = lambda cells: "| " + " | ".join(str(c).ljust(w) for c, w in zip(cells, widths)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "\n".join([line(headers), sep, *[line(r) for r in rows]])


# --------------------------------------------------------------------------
# section: corpus


def load_corpus() -> list[dict]:
    cases = []
    for case_dir in sorted(p for p in (GOLDEN / "cases").iterdir() if p.is_dir()):
        case = yaml.safe_load((case_dir / "case.yaml").read_text())
        fact_paths = sorted((case_dir / "facts").glob("*.json"))
        cases.append(
            {
                "id": str(case["id"]),
                "pack_rel": str(case["pack"]),
                "question": str(case["question"]),
                "effective": str(case["asOfEffective"]),
                "knowledge": str(case["asOfKnowledge"]),
                "fact_paths": fact_paths,
                "facts": [json.loads(p.read_text()) for p in fact_paths],
            }
        )
    return cases


def pack_path(pack_rel: str) -> Path:
    # Committed cases name a pack as `rulepacks/<name>/pack.yaml`, resolved
    # against the corpus's sibling directory.
    return GOLDEN.parent / pack_rel


def section_corpus() -> dict:
    if not (GOLDEN / "cases").is_dir():
        print("\n## corpus\n")
        print(f"SKIPPED — no corpus at {GOLDEN / 'cases'}. This section measures the "
              "committed teaching content, which an adopter deletes.")
        return {"skipped": "no examples/golden/cases — teaching content absent"}

    cases = load_corpus()
    pack_rels = sorted({c["pack_rel"] for c in cases})

    # (a) the one-time costs: read + parse the pack YAML, then validate the IR.
    pack_load: dict[str, dict] = {}
    packs: dict[str, dict] = {}
    for rel in pack_rels:
        path = pack_path(rel)
        raw = path.read_text()
        parsed = yaml.safe_load(raw)
        packs[rel] = parsed
        pack_load[rel] = {
            # `validate_pack` does not mutate its argument (asserted below), so
            # it is timed on the parsed pack directly. Timing it on a
            # `deepcopy` would fold the copy's cost into the validator's and
            # publish a number that is mostly `copy`.
            "read_parse_ms": best(lambda p=path: yaml.safe_load(p.read_text())) * 1000,
            "validate_ms": best(lambda d=parsed: validate_pack(d)) * 1000,
            "rules": len(parsed.get("rules", [])),
            "bytes": len(raw.encode()),
        }

    # (b) the per-case costs, three ways.
    per_case = []
    for case in cases:
        pack = packs[case["pack_rel"]]
        eff = normalize_point(case["effective"])
        kno = normalize_point(case["knowledge"])

        t_full = best(
            lambda: adjudicate(
                case["facts"], pack, case["effective"], case["knowledge"], case["question"]
            )
        )

        def _eval_only():
            result = evaluate_pack(case["facts"], pack, eff, kno)
            return build_receipt(result, pack, case["question"])

        t_eval = best(_eval_only)
        t_facts = best(lambda: [json.loads(p.read_text()) for p in case["fact_paths"]])

        per_case.append(
            {
                "id": case["id"],
                "pack": case["pack_rel"].split("/")[1],
                "facts": len(case["facts"]),
                "adjudicate_s": t_full,
                "evaluate_s": t_eval,
                "facts_io_s": t_facts,
            }
        )

    by_pack: dict[str, list[dict]] = {}
    for row in per_case:
        by_pack.setdefault(row["pack"], []).append(row)

    result = {
        "cases": len(per_case),
        "packs": {
            name: {
                "adjudicate": summarize([r["adjudicate_s"] for r in rows]),
                "evaluate": summarize([r["evaluate_s"] for r in rows]),
                "facts_io": summarize([r["facts_io_s"] for r in rows]),
                "load": pack_load[f"rulepacks/{name}/pack.yaml"],
            }
            for name, rows in sorted(by_pack.items())
        },
        "overall": {
            "adjudicate": summarize([r["adjudicate_s"] for r in per_case]),
            "evaluate": summarize([r["evaluate_s"] for r in per_case]),
            "facts_io": summarize([r["facts_io_s"] for r in per_case]),
        },
        "slowest": sorted(per_case, key=lambda r: -r["adjudicate_s"])[:5],
    }

    print("\n## corpus — per-case adjudication, by pack\n")
    rows = []
    for name, d in result["packs"].items():
        rows.append(
            [
                name,
                d["load"]["rules"],
                d["adjudicate"]["n"],
                f"{d['load']['read_parse_ms']:.2f}",
                f"{d['load']['validate_ms']:.3f}",
                f"{d['evaluate']['p50_ms']:.3f}",
                f"{d['adjudicate']['p50_ms']:.3f}",
                f"{d['adjudicate']['p95_ms']:.3f}",
                f"{d['adjudicate']['p99_ms']:.3f}",
            ]
        )
    print(
        table(
            rows,
            ["pack", "rules", "cases", "parse ms", "validate ms",
             "eval p50", "adj p50", "adj p95", "adj p99"],
        )
    )
    o = result["overall"]
    print(
        f"\nall {result['cases']} cases — adjudicate p50 {o['adjudicate']['p50_ms']:.3f} ms, "
        f"p95 {o['adjudicate']['p95_ms']:.3f} ms, p99 {o['adjudicate']['p99_ms']:.3f} ms, "
        f"max {o['adjudicate']['max_ms']:.3f} ms"
    )
    print(
        f"all {result['cases']} cases — evaluate+receipt only p50 {o['evaluate']['p50_ms']:.3f} ms, "
        f"p95 {o['evaluate']['p95_ms']:.3f} ms"
    )
    print(
        f"all {result['cases']} cases — reading the case's facts from disk p50 "
        f"{o['facts_io']['p50_ms']:.3f} ms"
    )
    print("slowest: " + ", ".join(f"{r['id']} {ms(r['adjudicate_s'])}ms" for r in result["slowest"]))
    return result


# --------------------------------------------------------------------------
# section: replay


def section_replay(runs: int = 3) -> dict:
    if not (GOLDEN / "cases").is_dir():
        print("\n## replay\n")
        print(f"SKIPPED — no corpus at {GOLDEN / 'cases'}. `duly-verify` refuses a "
              "missing corpus rather than reporting 'verified 0 cases', so there is "
              "nothing to time.")
        return {"skipped": "no examples/golden/cases — teaching content absent"}
    times = []
    out = ""
    rss = 0
    for _ in range(runs):
        before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        t0 = time.perf_counter()
        proc = subprocess.run(
            [sys.executable, "-m", "duly_assurance", "verify", "--golden", str(GOLDEN)],
            capture_output=True,
            text=True,
            cwd=REPO,
        )
        times.append(time.perf_counter() - t0)
        after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        rss = max(rss, after if after > before else before)
        out = proc.stdout.strip()
        if proc.returncode != 0:
            return {"error": proc.stdout + proc.stderr}
    cases = int(out.split()[1]) if out.startswith("verified") else 0
    result = {
        "runs": runs,
        "wall_s": times,
        "best_s": min(times),
        "cases": cases,
        "per_case_ms": min(times) / cases * 1000 if cases else float("nan"),
        "child_maxrss_mb": rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024,
    }
    print("\n## replay — duly-verify over the whole corpus\n")
    print(f"{out} in {min(times):.2f} s (best of {runs}: "
          + ", ".join(f"{t:.2f}" for t in times) + ")")
    print(f"= {result['per_case_ms']:.1f} ms per case end to end, including process start, "
          "pack parsing, fact I/O and byte comparison")
    print(f"peak RSS of the verify process: {result['child_maxrss_mb']:.0f} MB")
    return result


# --------------------------------------------------------------------------
# section: memory


def largest_corpus_case() -> tuple[dict, dict] | None:
    if not (GOLDEN / "cases").is_dir():
        return None
    cases = load_corpus()
    case = max(cases, key=lambda c: (len(c["facts"]), sum(len(json.dumps(f)) for f in c["facts"])))
    pack = yaml.safe_load(pack_path(case["pack_rel"]).read_text())
    return case, pack


def section_memory() -> dict:
    result: dict = {}

    # tracemalloc, not ru_maxrss, for the per-adjudication number. ru_maxrss is
    # a process-wide high-water mark that includes the interpreter, every
    # imported module and any allocator slack, so it cannot answer "what does
    # one adjudication cost"; tracemalloc measures the Python allocations made
    # inside the block being traced and nothing else. ru_maxrss is the right
    # instrument for the other question — how much memory a deployment must
    # provision — so both appear, each answering the one it can.
    pair = largest_corpus_case()
    if pair is not None:
        case, pack = pair
        adjudicate(case["facts"], pack, case["effective"], case["knowledge"], case["question"])
        tracemalloc.start()
        tracemalloc.reset_peak()
        adjudicate(case["facts"], pack, case["effective"], case["knowledge"], case["question"])
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result["largest_case"] = {
            "id": case["id"],
            "facts": len(case["facts"]),
            "pack": case["pack_rel"].split("/")[1],
            "peak_kib": peak / 1024,
            "retained_kib": current / 1024,
        }
        print("\n## memory\n")
        print(
            f"tracemalloc peak for one adjudication of {case['id']} "
            f"({len(case['facts'])} facts, pack {case['pack_rel'].split('/')[1]}): "
            f"{peak / 1024:.1f} KiB (retained after return: {current / 1024:.1f} KiB)"
        )

        # The pack held in memory, which a service pays once rather than per call.
        tracemalloc.start()
        tracemalloc.reset_peak()
        held = yaml.safe_load(pack_path(case["pack_rel"]).read_text())
        resident, peak_pack = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        result["pack"] = {"resident_kib": resident / 1024, "parse_peak_kib": peak_pack / 1024}
        print(
            f"parsed pack ({len(held.get('rules', []))} rules) held in memory: "
            f"{resident / 1024:.0f} KiB; peak during parsing: {peak_pack / 1024:.0f} KiB"
        )
    else:
        print("\n## memory\n")
        print("corpus absent — per-adjudication figure skipped")

    # The floor: a whole process that imports the kernel and adjudicates once.
    # This is the number an ops person sizes a container with, and it is
    # dominated by the interpreter, not by duly.
    probe = (
        "import json,resource,sys,yaml;"
        "from duly_kernel.api import adjudicate;"
        f"case=yaml.safe_load(open({str(FIXTURE_CASE / 'case.yaml')!r}));"
        f"import glob;facts=[json.load(open(p)) for p in sorted(glob.glob({str(FIXTURE_CASE / 'facts' / '*.json')!r}))];"
        f"pack=yaml.safe_load(open({str(FIXTURE_PACK)!r}));"
        "r=adjudicate(facts,pack,str(case['asOfEffective']),str(case['asOfKnowledge']),str(case['question']));"
        "print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)"
    )
    proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, cwd=REPO)
    if proc.returncode == 0:
        raw = int(proc.stdout.strip().splitlines()[-1])
        mb = raw / (1024 * 1024) if sys.platform == "darwin" else raw / 1024
        result["process_floor_mb"] = mb
        print(f"whole-process RSS for import + one adjudication (fixture pack): {mb:.1f} MB")
    else:
        result["process_floor_error"] = proc.stderr[-2000:]
        print("process-floor probe failed:\n" + proc.stderr[-800:])
    return result


# --------------------------------------------------------------------------
# section: scaling
#
# Synthetic, in memory, committed nowhere. The base is fixtures/pack.yaml —
# toolkit content, so this section still runs after `git rm -r examples/`.


def _letters(k: int, width: int = 3) -> str:
    """Base-26 in capitals. Rule ids are letters and hyphens with at most a
    trailing two-digit sequence (spec/rule-ir.md, "Rule ids"), so a synthetic
    family cannot count in decimal — the same constraint a real pack has."""
    out = []
    for _ in range(width):
        out.append(chr(ord("A") + k % 26))
        k //= 26
    return "".join(reversed(out))


#: How many synthetic rules share one concluded attribute in the "spread"
#: shape. The six committed teaching packs run 3–10 rules over 2–3 attributes,
#: so eight is the realistic end of the range; `PER_ATTR = None` puts every
#: rule on one attribute, which is the other end.
SPREAD_PER_ATTR = 8


def synth_pack(extra_rules: int, per_attr: int | None = None) -> dict:
    """The fixture pack plus `extra_rules` synthetic rules.

    Each synthetic rule binds two variables and evaluates one comparison, so
    it costs what a real rule costs; the thresholds are spread so roughly half
    the guards pass and half fail, which exercises both paths. They conclude
    `fx:tier…` attributes no decision reads, so the receipt does not grow with
    the pack — these curves are pack cost and nothing else.

    `per_attr` is the shape knob, and it is not cosmetic. With `None` every
    synthetic rule concludes **one** attribute; with an integer they spread
    over `extra_rules / per_attr` of them. Two of the checks in `validate_pack`
    are quadratic *within* an attribute group, so the same rule count costs
    very different amounts under the two shapes — which is why both are
    measured rather than one being called "the" curve.
    """
    pack = yaml.safe_load(FIXTURE_PACK.read_text())
    for k in range(extra_rules):
        group = 0 if per_attr is None else k // per_attr
        seq = k if per_attr is None else k % per_attr
        pack["rules"].append(
            {
                "id": f"FX-SYN-{_letters(k)}",
                "version": "1.0.0",
                "priority": seq + 1,
                "citation": {"text": "synthetic benchmark rule (fictional)"},
                "effectiveFrom": "1900-01-01",
                "given": {
                    "widget": {"entityType": "fx:Widget"},
                    "score": {"attribute": "fx:score"},
                },
                "when": [f"score >= {seq * 2}"],
                "then": {
                    "entity": "widget",
                    "attribute": f"fx:tier{_letters(group)}",
                    "value": {"kind": "decimal", "value": str(k)},
                },
            }
        )
    return pack


def synth_facts(base: list[dict], extra: int) -> list[dict]:
    """The case's own facts plus `extra` machine facts on distinct attributes
    of the same entity. They bind to no rule, so they measure what the engine
    pays to carry a fact it does not use: liveness filtering, the abstention
    policy, conflict grouping and the binding indexes."""
    facts = [copy.deepcopy(f) for f in base]
    template = copy.deepcopy(base[0])
    for i in range(extra):
        f = copy.deepcopy(template)
        f["attribute"] = f"fx:filler{i:05d}"
        f["id"] = f"urn:duly:fact:sha256:{i:064d}"
        f["contentHash"] = f"{i:064d}"
        f["value"] = {"kind": "decimal", "value": str(i)}
        f["confidence"] = {"score": 1.0, "method": "raw"}
        facts.append(f)
    return facts


def section_scaling() -> dict:
    case = yaml.safe_load((FIXTURE_CASE / "case.yaml").read_text())
    base_facts = [json.loads(p.read_text()) for p in sorted((FIXTURE_CASE / "facts").glob("*.json"))]
    eff = normalize_point(str(case["asOfEffective"]))
    kno = normalize_point(str(case["asOfKnowledge"]))
    question = str(case["question"])

    rule_data: dict[str, list[dict]] = {}
    for label, per_attr in (("spread", SPREAD_PER_ATTR), ("concentrated", None)):
        shape = (
            f"{SPREAD_PER_ATTR} rules per concluded attribute"
            if per_attr
            else "every rule concluding the same attribute"
        )
        print(f"\n## scaling — rule count, {label} ({shape}); facts fixed at 2\n")
        rows = []
        data = []
        for extra in (0, 10, 50, 100, 250, 500, 1000, 2000):
            pack = synth_pack(extra, per_attr)
            total = len(pack["rules"])
            t_validate = best(lambda p=pack: validate_pack(p))

            def _ev(p=pack):
                return build_receipt(evaluate_pack(base_facts, p, eff, kno), p, question)

            t_eval = best(_ev)
            t_full = best(
                lambda p=pack: adjudicate(
                    base_facts, p, str(case["asOfEffective"]),
                    str(case["asOfKnowledge"]), question
                ),
            )
            data.append(
                {"rules": total, "validate_ms": t_validate * 1000,
                 "evaluate_ms": t_eval * 1000, "adjudicate_ms": t_full * 1000}
            )
            rows.append([total, ms(t_validate), ms(t_eval), ms(t_full),
                         f"{t_eval / total * 1000:.4f}"])
        print(table(rows, ["rules", "validate ms", "evaluate ms", "adjudicate ms", "eval ms/rule"]))
        rule_data[label] = data

    print("\n## scaling — fact count (pack fixed at 6 rules)\n")
    fixture_pack = yaml.safe_load(FIXTURE_PACK.read_text())
    fact_rows = []
    fact_data = []
    for extra in (0, 10, 50, 100, 250, 500, 1000, 2000):
        facts = synth_facts(base_facts, extra)

        def _ev(f=facts):
            return build_receipt(
                evaluate_pack(f, fixture_pack, eff, kno), fixture_pack, question
            )

        t_eval = best(_ev)
        fact_data.append({"facts": len(facts), "evaluate_ms": t_eval * 1000})
        fact_rows.append([len(facts), ms(t_eval), f"{t_eval / len(facts) * 1000:.4f}"])
    print(table(fact_rows, ["facts", "evaluate ms", "eval ms/fact"]))

    print("\n## scaling — both together\n")
    both_rows = []
    both_data = []
    for r, f in ((10, 10), (100, 100), (500, 500), (1000, 1000)):
        pack = synth_pack(r, SPREAD_PER_ATTR)
        facts = synth_facts(base_facts, f)

        def _ev(p=pack, fs=facts):
            return build_receipt(evaluate_pack(fs, p, eff, kno), p, question)

        t_eval = best(_ev)
        both_data.append({"rules": len(pack["rules"]), "facts": len(facts),
                          "evaluate_ms": t_eval * 1000})
        both_rows.append([len(pack["rules"]), len(facts), ms(t_eval)])
    print(table(both_rows, ["rules", "facts", "evaluate ms"]))

    return {"rules": rule_data, "facts": fact_data, "both": both_data}


# --------------------------------------------------------------------------


def machine() -> dict:
    info = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    if sys.platform == "darwin":
        for key, label in (("machdep.cpu.brand_string", "cpu"), ("hw.memsize", "memory_bytes")):
            try:
                info[label] = subprocess.run(
                    ["sysctl", "-n", key], capture_output=True, text=True
                ).stdout.strip()
            except OSError:  # pragma: no cover
                pass
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="capacity_bench.py",
        description="Measure duly's reference kernel from outside it (docs/capacity-envelope.md).",
    )
    parser.add_argument(
        "--only",
        choices=["corpus", "replay", "memory", "scaling"],
        action="append",
        help="run one section (repeatable); default is all four",
    )
    parser.add_argument("--json", help="also write the raw numbers to this path")
    args = parser.parse_args(argv)
    wanted = args.only or ["corpus", "replay", "memory", "scaling"]

    info = machine()
    print("# duly capacity bench")
    print(f"\npython {info['python']} ({info['implementation']}) on {info['platform']}")
    if "cpu" in info:
        mem = int(info.get("memory_bytes") or 0) / (1024**3)
        print(f"{info['cpu']}, {mem:.0f} GiB RAM")
    print(f"best of {REPEATS} runs per measurement")

    out = {"machine": info, "repeats": REPEATS}
    if "corpus" in wanted:
        out["corpus"] = section_corpus()
    if "replay" in wanted:
        out["replay"] = section_replay()
    if "memory" in wanted:
        out["memory"] = section_memory()
    if "scaling" in wanted:
        out["scaling"] = section_scaling()

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
        print(f"\nraw numbers written to {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
