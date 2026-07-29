"""Knowledge-time travel: the M2 headline behavior.

A correction (supersedes) recorded at T2 must be invisible to any projection
whose knowledge horizon is before T2, and the original must remain visible
there — history is never rewritten, only appended to (D6/D7).
"""

from duly_store.store import FactStore

from storetest_helpers import CASE_ID, correction, load_spec_facts

T1 = "2026-07-28T14:06:02Z"  # original fact-notice-mailed recordedAt
T2 = "2026-07-30T09:00:00Z"  # first correction
T3 = "2026-08-02T12:00:00Z"  # correction of the correction

ATTR = "nc:noticeMailedDate"


def build_chain():
    """The four spec facts, plus a two-step correction chain on the
    notice-mailed date: 2026-07-25 (F1) -> 2026-07-20 (F2) -> 2026-07-22 (F3)."""
    facts = load_spec_facts()
    f1 = next(f for f in facts if f["attribute"] == ATTR)
    f2 = correction(
        f1, value={"kind": "date", "value": "2026-07-20"}, recorded_at=T2, supersedes=f1["id"]
    )
    f3 = correction(
        f2, value={"kind": "date", "value": "2026-07-22"}, recorded_at=T3, supersedes=f2["id"]
    )
    store = FactStore.in_memory()
    store.init_schema()
    for fact in facts + [f2, f3]:
        store.ingest(fact)
    return store, f1, f2, f3


def mailed_facts(store, knowledge):
    return [f for f in store.as_of(CASE_ID, knowledge) if f["attribute"] == ATTR]


def test_before_correction_sees_original():
    store, f1, f2, f3 = build_chain()
    live = mailed_facts(store, "2026-07-30T08:59:59Z")  # knowledge < T2
    assert [f["id"] for f in live] == [f1["id"]]
    assert live[0]["value"]["value"] == "2026-07-25"


def test_at_and_after_correction_sees_only_correction():
    store, f1, f2, f3 = build_chain()
    for knowledge in (T2, "2026-07-31T00:00:00Z"):  # T2 <= knowledge < T3
        live = mailed_facts(store, knowledge)
        assert [f["id"] for f in live] == [f2["id"]]
        assert live[0]["value"]["value"] == "2026-07-20"
        assert live[0]["supersedes"] == f1["id"]


def test_correction_of_correction():
    store, f1, f2, f3 = build_chain()
    live = mailed_facts(store, T3)  # knowledge >= T3
    assert [f["id"] for f in live] == [f3["id"]]
    assert live[0]["value"]["value"] == "2026-07-22"

    # Exactly one live mailed-date fact at every horizon — never zero, never two.
    for knowledge in (T1, "2026-07-29T00:00:00Z", T2, "2026-08-01T00:00:00Z", T3, "2027-01-01"):
        assert len(mailed_facts(store, knowledge)) == 1


def test_other_facts_unaffected_by_the_chain():
    store, f1, f2, f3 = build_chain()
    for knowledge in (T1, T2, T3):
        projected = store.as_of(CASE_ID, knowledge)
        assert len(projected) == 4  # 3 untouched facts + exactly 1 mailed-date


def test_history_walks_the_whole_chain():
    store, f1, f2, f3 = build_chain()
    for start in (f1["id"], f2["id"], f3["id"]):
        events = store.history(start)
        kinds = [(e["event_kind"], e["fact_id"]) for e in events]
        assert kinds == [
            ("asserted", f1["id"]),
            ("asserted", f2["id"]),
            ("superseded", f1["id"]),
            ("asserted", f3["id"]),
            ("superseded", f2["id"]),
        ]
    # The superseded events carry the superseding fact id and its recordedAt.
    events = store.history(f1["id"])
    superseded_f1 = events[2]
    assert superseded_f1["supersedes"] == f2["id"]
    assert superseded_f1["recorded_at"] == T2


def test_replay_is_stable_after_later_writes():
    """Appending F3 must not change what any earlier horizon returns."""
    facts = load_spec_facts()
    f1 = next(f for f in facts if f["attribute"] == ATTR)
    f2 = correction(
        f1, value={"kind": "date", "value": "2026-07-20"}, recorded_at=T2, supersedes=f1["id"]
    )
    store = FactStore.in_memory()
    store.init_schema()
    for fact in facts + [f2]:
        store.ingest(fact)

    horizon = "2026-07-29T00:00:00Z"
    before = store.as_of(CASE_ID, horizon)

    f3 = correction(
        f2, value={"kind": "date", "value": "2026-07-22"}, recorded_at=T3, supersedes=f2["id"]
    )
    store.ingest(f3)
    assert store.as_of(CASE_ID, horizon) == before
