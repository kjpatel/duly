"""API tests for the demo's receipt viewer (duly_demo/receipts_api.py).

These run against a content root assembled from
[`fixtures/`](../../fixtures/README.md) — the viewer is toolkit (M5 plan, D2),
so its suite must survive `git rm -r examples/` rather than stop being
collected. The receipts it opens are real ones, built and sealed by
`fixtures/build.py`; what changed is who owns them, not whether they are
genuine.

The forgery cases below are the ones that earn the module. A receipt that has
been edited fails the hash check; a receipt that has been edited *and*
re-hashed passes it, and is caught only by re-adjudication. Both are asserted,
because the second is the one that makes verification worth doing.

Run from the repo root:
    PATH="/opt/homebrew/bin:$PATH" uv run pytest duly_demo/tests -q
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from demotest_helpers import CASE, build_content_root, reload_demo  # noqa: E402
from duly_kernel.receipt import content_hash  # noqa: E402

GOLDEN: Path  # the content root's corpus, bound per session by `client`


@pytest.fixture(scope="session")
def content_root(tmp_path_factory) -> Path:
    """The demo's content, built from `fixtures/` — see demotest_helpers."""
    return build_content_root(tmp_path_factory.mktemp("content"))


@pytest.fixture
def client(content_root, monkeypatch):
    """A viewer serving the fixture content root rather than this repository.

    The surfaces bind their roots at *import*, which is right for a server —
    import is startup — so the modules are reloaded in dependency order after
    the environment moves, exactly as `test_content_roots` does it.
    """
    global GOLDEN
    monkeypatch.setenv("DULY_DEMO_CONTENT", str(content_root))
    monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
    GOLDEN = content_root / "golden"

    reload_demo()
    import duly_demo.app

    with TestClient(duly_demo.app.app) as c:
        yield c

    # Restore, or every later module in the directory run inherits a demo
    # pointed at a temp directory — the import-time binding cuts both ways,
    # and `monkeypatch` unsets the variable without un-reloading anything.
    monkeypatch.undo()
    reload_demo()


def _receipt(case_id: str = CASE) -> dict:
    return json.loads((GOLDEN / "receipts" / f"{case_id}.json").read_text())


def _fact_texts(case_id: str = CASE) -> list[str]:
    return [p.read_text() for p in sorted((GOLDEN / "cases" / case_id / "facts").glob("*.json"))]


def _rehash(receipt: dict) -> dict:
    """Re-seal a receipt so it is internally consistent — what a forger does."""
    receipt["receiptSha256"] = content_hash(receipt, "receiptSha256")
    receipt["id"] = f"urn:duly:receipt:sha256:{receipt['receiptSha256']}"
    return receipt


def _inspect(client, *documents: str):
    res = client.post("/api/receipts/inspect", json={"documents": list(documents)})
    assert res.status_code == 200, res.text
    return res.json()


def _checks(view: dict) -> dict[str, str]:
    return {c["id"]: c["state"] for c in view["verification"]["checks"]}


def yaml_name(pack_path: Path) -> str:
    """The name a pack file *declares* — which is not its directory's name."""
    import yaml

    return yaml.safe_load(pack_path.read_text())["pack"]["name"]


class TestCorpusIndex:
    def test_every_committed_receipt_is_listed(self, client):
        body = client.get("/api/receipts/corpus").json()
        on_disk = len(list((GOLDEN / "receipts").glob("*.json")))
        assert body["count"] == on_disk
        assert len(body["cases"]) == on_disk

    def test_rows_carry_what_the_list_shows(self, client):
        body = client.get("/api/receipts/corpus").json()
        row = next(r for r in body["cases"] if r["caseId"] == CASE)
        receipt = _receipt()
        assert row["receiptSha256"] == receipt["receiptSha256"]
        assert row["pack"] == receipt["rulePack"]["name"]
        assert row["attribute"] == receipt["decision"]["attribute"]
        assert row["attributeShort"] == "permitted"

    def test_packs_are_offered_as_filters(self, client):
        body = client.get("/api/receipts/corpus").json()
        assert "duly-fixture-pack" in body["packs"]
        assert body["packs"] == sorted(set(body["packs"]))


class TestGoldenCaseView:
    def test_a_committed_case_verifies_on_every_check(self, client):
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        assert _checks(view) == {"receiptHash": "pass", "facts": "pass", "replay": "pass"}
        assert view["verification"]["verdict"] == "pass"

    def test_facts_and_pack_resolve_from_the_repository(self, client):
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        assert view["resolution"]["state"] == "resolved"
        assert view["resolution"]["facts"]["source"] == f"golden/cases/{CASE}/facts"
        assert view["resolution"]["pack"]["state"] == "resolved"

    def test_the_report_is_the_kernels_sections(self, client):
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        titles = [s["title"] for s in view["report"]]
        assert titles == [
            None,
            "Conclusion",
            "Reasoning",
            "Rules applied",
            "Evidence",
            "Integrity and replay",
        ]

    def test_blocks_are_json_serializable_and_tagged(self, client):
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        tags = {b["tag"] for s in view["report"] for b in s["blocks"]}
        assert tags <= {"para", "kv", "steps", "subhead", "code"}
        json.dumps(view["report"])  # must survive the wire unchanged

    def test_evidence_quotes_reach_the_report(self, client):
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        reasoning = next(s for s in view["report"] if s["title"] == "Reasoning")
        evidence = [e for b in reasoning["blocks"] for s in b["steps"] for e in s["evidence"]]
        assert evidence, "a case with pinned facts should cite them in its reasoning"

    def test_every_case_in_the_corpus_replays(self, client):
        # `duly_assurance verify` proves replay for the corpus directly; this
        # proves it *through the viewer*, so a bug in this module's own
        # resolution — the pack it picks, the facts it gathers — cannot hide
        # behind a green verifier run.
        body = client.get("/api/receipts/corpus").json()
        assert body["count"] >= 4
        for row in body["cases"]:
            view = client.get(f"/api/receipts/corpus/{row['caseId']}").json()
            assert view["verification"]["verdict"] == "pass", row["caseId"]

    def test_an_unknown_case_is_404(self, client):
        assert client.get("/api/receipts/corpus/no-such-case").status_code == 404

    def test_a_traversing_case_id_is_refused(self, client):
        assert client.get("/api/receipts/corpus/..%2F..%2Fetc%2Fpasswd").status_code == 404


class TestTampering:
    def test_an_edited_receipt_fails_its_own_hash(self, client):
        receipt = _receipt()
        receipt["decision"]["value"]["value"] = True  # left un-resealed
        view = _inspect(client, json.dumps(receipt), *_fact_texts())
        assert _checks(view)["receiptHash"] == "fail"
        assert view["verification"]["verdict"] == "fail"

    def test_an_edited_receipt_is_caught_even_when_resealed(self, client):
        # The case the whole module exists for: hash and facts are impeccable,
        # and the decision is still a lie. Only re-running the rules finds it.
        receipt = _receipt()
        receipt["decision"]["value"]["value"] = True
        view = _inspect(client, json.dumps(_rehash(receipt)), *_fact_texts())
        assert _checks(view) == {"receiptHash": "pass", "facts": "pass", "replay": "fail"}
        assert view["verification"]["verdict"] == "fail"
        replay = next(c for c in view["verification"]["checks"] if c["id"] == "replay")
        assert replay["expected"] != replay["actual"]

    def test_an_altered_fact_is_caught_by_its_content_hash(self, client):
        facts = [json.loads(t) for t in _fact_texts()]
        target = next(f for f in facts if f["value"].get("kind") == "decimal")
        target["value"]["value"] = "9999"
        view = _inspect(client, json.dumps(_receipt()), json.dumps(facts))
        assert _checks(view)["facts"] == "fail"
        check = next(c for c in view["verification"]["checks"] if c["id"] == "facts")
        assert len(check["tampered"]) == 1

    def test_a_missing_fact_is_named(self, client):
        facts = [json.loads(t) for t in _fact_texts()]
        dropped = facts.pop()
        view = _inspect(client, json.dumps(_receipt()), json.dumps(facts))
        check = next(c for c in view["verification"]["checks"] if c["id"] == "facts")
        assert check["state"] == "fail"
        assert check["missing"] == [dropped["id"]]


class TestNumericFidelity:
    """A content hash is over bytes, so the parse has to happen once.

    JavaScript has a single number type: a fact's ``"score": 1.0`` survives
    ``JSON.parse``/``JSON.stringify`` as ``1``, which canonicalizes
    differently and hashes differently. The viewer therefore sends raw text
    and lets Python do the only parse. These tests pin that, because the
    symptom of regressing it is every genuine fact reported as tampered with
    — an alarming, entirely false result.
    """

    def test_facts_are_hashed_from_the_bytes_supplied(self, client):
        view = _inspect(client, json.dumps(_receipt()), *_fact_texts())
        assert _checks(view)["facts"] == "pass"

    def test_a_float_flattened_to_an_int_is_a_different_document(self):
        fact = json.loads(_fact_texts()[0])
        assert fact["confidence"]["score"] == 1.0
        assert content_hash(fact, "contentHash") == fact["contentHash"]
        flattened = copy.deepcopy(fact)
        flattened["confidence"]["score"] = 1  # what a JS round trip does
        assert content_hash(flattened, "contentHash") != fact["contentHash"]

    def test_documents_may_arrive_in_any_arrangement(self, client):
        # One blob per file, or one blob holding them all — the caller should
        # never have to re-serialize to fit a shape, since re-serializing is
        # exactly what corrupts the bytes.
        per_file = _inspect(client, json.dumps(_receipt()), *_fact_texts())
        one_array = _inspect(
            client, "[" + ",".join([json.dumps(_receipt()), *_fact_texts()]) + "]"
        )
        assert _checks(per_file) == _checks(one_array) == {
            "receiptHash": "pass",
            "facts": "pass",
            "replay": "pass",
        }


class TestStandaloneTier:
    def test_a_receipt_from_outside_still_verifies_its_own_hash(self, client):
        receipt = _receipt()
        receipt["caseId"] = "case:acme-prod:loan-88213"
        view = _inspect(client, json.dumps(_rehash(receipt)))
        assert view["knownCase"] is None
        assert _checks(view) == {
            "receiptHash": "pass",
            "facts": "unavailable",
            "replay": "unavailable",
        }
        assert view["verification"]["verdict"] == "partial"

    def test_missing_evidence_is_reported_not_omitted(self, client):
        receipt = _receipt()
        receipt["caseId"] = "case:acme-prod:loan-88213"
        view = _inspect(client, json.dumps(_rehash(receipt)))
        check = next(c for c in view["verification"]["checks"] if c["id"] == "facts")
        assert "pinned by hash" in check["detail"]
        evidence = next(s for s in view["report"] if s["title"] == "Evidence")
        rendered = " ".join(
            b.get("text", "") for b in evidence["blocks"] if b["tag"] == "para"
        )
        assert "was not supplied for rendering" in rendered

    def test_a_pasted_corpus_receipt_resolves_its_own_facts(self, client):
        # The paste has no facts, but the corpus does — and a receipt that is
        # bit-identical to a committed one is that case, so say so.
        view = _inspect(client, json.dumps(_receipt()))
        assert view["knownCase"] == CASE
        assert view["resolution"]["facts"]["state"] == "resolved"
        assert _checks(view)["replay"] == "pass"

    def test_a_document_that_is_not_a_receipt_is_refused(self, client):
        res = client.post(
            "/api/receipts/inspect", json={"documents": [json.dumps({"hello": "world"})]}
        )
        assert res.status_code == 422
        assert "receiptSha256" in res.json()["detail"]

    def test_invalid_json_names_the_document(self, client):
        res = client.post("/api/receipts/inspect", json={"documents": ["{not json"]})
        assert res.status_code == 422
        assert "Document 1" in res.json()["detail"]


class TestPackResolution:
    def test_a_pack_name_from_a_pasted_receipt_never_becomes_a_path(self, client):
        """`rulePack.name` is caller data on this route, and it is about to be
        joined into a path. A name that is not a directory name cannot be a
        pack in this working tree either, so it is refused before the join
        rather than allowed to walk out of `rulepacks/`."""
        for name in ("../../etc", "..", "/etc", "Not A Pack"):
            receipt = _receipt()
            receipt["rulePack"]["name"] = name
            view = _inspect(client, json.dumps(_rehash(receipt)))
            assert view["resolution"]["pack"]["state"] == "unavailable"
            assert "not a rule-pack name" in view["resolution"]["pack"]["reason"]
            assert _checks(view)["replay"] == "unavailable"

    def test_a_pack_directory_named_differently_from_pack_name_resolves(
        self, tmp_path, monkeypatch
    ):
        """The viewer resolves a receipt's pack by what packs *declare*, not by
        where they sit.

        `rulepacks/<directory>/pack.yaml` and `pack.name` are two different
        strings. Duly's own packs make them equal, so building the path from
        the receipt's name passed every test here while answering
        `replay: unavailable` for any adopter who named the directory anything
        else — and unavailable is the answer that looks like a missing pack
        rather than like a lookup that could never have succeeded.

        So this content root is deliberately mis-named: the pack directory is
        `an-adopters-directory-name` while the pack inside it still declares
        `duly-fixture-pack`, which is what every receipt in the corpus carries.
        """
        root = build_content_root(tmp_path / "content")
        pack_dir = root / "rulepacks" / "duly-fixture-pack"
        renamed = pack_dir.with_name("an-adopters-directory-name")
        pack_dir.rename(renamed)
        assert not pack_dir.exists()
        assert yaml_name(renamed / "pack.yaml") == "duly-fixture-pack"

        # Everything that refers to the pack *by path* follows the directory;
        # only the receipts, which refer to it by name, do not. That asymmetry
        # is the situation under test, not an inconsistency to tidy away.
        for case_yaml in (root / "golden" / "cases").glob("*/case.yaml"):
            case_yaml.write_text(
                case_yaml.read_text().replace(
                    "rulepacks/duly-fixture-pack/", f"rulepacks/{renamed.name}/"
                )
            )

        monkeypatch.setenv("DULY_DEMO_CONTENT", str(root))
        monkeypatch.delenv("DULY_DEMO_FORCE_FIXTURE", raising=False)
        reload_demo()
        try:
            import duly_demo.app

            with TestClient(duly_demo.app.app) as c:
                view = c.get(f"/api/receipts/corpus/{CASE}").json()
        finally:
            monkeypatch.undo()
            reload_demo()

        pack_status = view["resolution"]["pack"]
        assert pack_status["state"] == "resolved", pack_status
        assert pack_status["source"] == f"rulepacks/{renamed.name}/pack.yaml"
        # Resolution is not the claim; replay is. The pack was found, so the
        # receipt is re-adjudicated and compared byte-for-byte.
        assert _checks(view)["replay"] == "pass"
        assert view["verification"]["verdict"] == "pass"
        assert view["report"], "a resolved pack should render report sections"

    def test_a_moved_pack_version_is_refused_not_substituted(self, client, monkeypatch):
        # Rendering rule text out of a pack version the receipt never saw
        # would attribute descriptions to rules that never carried them. The
        # gap is reported instead.
        from duly_demo import receipts_api

        real = receipts_api.yaml.safe_load

        def shifted(text):
            pack = real(text)
            if isinstance(pack, dict) and isinstance(pack.get("pack"), dict):
                pack["pack"]["version"] = "9999.0.0"
            return pack

        monkeypatch.setattr(receipts_api.yaml, "safe_load", shifted)
        view = client.get(f"/api/receipts/corpus/{CASE}").json()

        assert view["resolution"]["pack"]["state"] == "moved"
        assert view["resolution"]["pack"]["workingTreeVersion"] == "9999.0.0"
        assert _checks(view)["replay"] == "unavailable"
        assert view["verification"]["verdict"] == "partial"


class TestSemantics:
    def test_a_receipt_at_unimplemented_semantics_is_not_replayed(self, client):
        """spec/compatibility.md C3. The receipt is re-sealed, so its hash and
        its facts check out — which is exactly the case worth getting right: a
        pass here would be this kernel answering a question about *its* meaning
        and reporting it as the receipt's."""
        receipt = _receipt()
        receipt["engine"]["version"] = "0.0.2"
        view = _inspect(client, json.dumps(_rehash(receipt)), *_fact_texts())

        checks = _checks(view)
        assert checks["receiptHash"] == "pass"
        assert checks["facts"] == "pass"
        assert checks["replay"] == "unavailable"
        assert view["verification"]["verdict"] == "partial"
        detail = next(
            c["detail"] for c in view["verification"]["checks"] if c["id"] == "replay"
        )
        assert "0.0.2" in detail


class TestExports:
    def test_markdown_report_renders_for_a_corpus_case(self, client):
        res = client.get(f"/api/receipts/corpus/{CASE}/report?format=md")
        assert res.status_code == 200
        assert res.text.startswith("# Decision audit report")
        assert "Integrity and replay" in res.text

    def test_the_markdown_matches_the_kernel_renderer(self, client, content_root):
        # Same inputs, same renderer: this route resolves them from the corpus
        # rather than from a live scenario, and must not differ otherwise.
        import yaml

        from duly_kernel.report import render_report_markdown

        pack_name = _receipt()["rulePack"]["name"]
        pack = yaml.safe_load(
            (content_root / "rulepacks" / pack_name / "pack.yaml").read_text()
        )
        expected = render_report_markdown(
            _receipt(), [json.loads(t) for t in _fact_texts()], pack
        )
        res = client.get(f"/api/receipts/corpus/{CASE}/report?format=md")
        assert res.text == expected

    def test_pdf_report_renders(self, client):
        res = client.get(f"/api/receipts/corpus/{CASE}/report?format=pdf")
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF")

    def test_receipt_json_download_is_the_committed_bytes(self, client):
        res = client.get(f"/api/receipts/corpus/{CASE}/receipt.json")
        assert res.status_code == 200
        assert res.json() == _receipt()

    def test_an_unknown_format_is_refused(self, client):
        res = client.get(f"/api/receipts/corpus/{CASE}/report?format=docx")
        assert res.status_code == 422


class TestWithoutTheKernel:
    """The demo must start and degrade when `duly_kernel` is not importable.

    This module is the only one of the four that cannot do its job at all
    without the kernel, which makes it the one most likely to reach for a
    module-scope import — and `duly_demo/app.py` includes its router
    unconditionally, so such an import would take all four pages down at
    once. Both halves are asserted: the module imports, and its checks report
    "not checked" naming the kernel rather than raising.
    """

    def test_the_demo_imports_without_the_kernel(self):
        # A child interpreter, because blocking duly_kernel in this one would
        # take it away from the rest of the suite.
        import subprocess

        program = (
            "import sys\n"
            "class Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] == 'duly_kernel':\n"
            "            raise ImportError(name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "import duly_demo.app\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_every_check_says_the_kernel_is_missing_rather_than_raising(
        self, client, monkeypatch
    ):
        from duly_demo import receipts_api

        monkeypatch.setattr(receipts_api, "_kernel", lambda name: None)
        view = client.get(f"/api/receipts/corpus/{CASE}").json()
        assert _checks(view) == {
            "receiptHash": "unavailable",
            "facts": "unavailable",
            "replay": "unavailable",
        }
        assert view["verification"]["verdict"] == "partial"
        assert "kernel" in view["verification"]["headline"]
        for check in view["verification"]["checks"]:
            assert "duly_kernel" in check["detail"]
        # No report sections rather than a thinner report that looks complete.
        assert view["report"] == []


class TestTheViewerIsServedAndLinked:
    def test_the_page_is_served(self, client):
        res = client.get("/receipt")
        assert res.status_code == 200
        assert "receipt.js" in res.text

    def test_the_other_surfaces_link_to_it(self, client):
        for path in ("/", "/rules"):
            assert 'href="/receipt"' in client.get(path).text
