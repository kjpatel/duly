"""Compiling a DMN document into the rule IR: bindings, hit policies, values."""

from __future__ import annotations

import pytest

from duly_dmn import compile_file, compile_source
from duly_dmn.errors import DmnCompileError
from dmntest_helpers import FIXTURE_DMN, FIXTURE_REFUSALS, fixture_value_kinds, minimal_dmn


@pytest.fixture(scope="module")
def fixture_pack():
    """The toolkit's own DMN document, compiled.

    Its subject is the compiler, so it compiles `fixtures/dmn/widget-fee.dmn`
    rather than the TRID teaching table: a suite whose only input is example
    content stops being collected when that content is deleted, which reads
    exactly like success (CLAUDE.md).
    """
    return compile_file(FIXTURE_DMN)


def rule(pack, rule_id):
    return next(r for r in pack["rules"] if r["id"] == rule_id)


def test_pack_metadata_comes_from_the_duly_extension(fixture_pack):
    assert fixture_pack["pack"]["name"] == "duly-fixture-dmn"
    assert fixture_pack["pack"]["ontology"] == "duly-fixture"
    # `<description>` is native DMN; the compiler uses DMN's own vocabulary
    # wherever DMN has one.
    assert fixture_pack["pack"]["description"] == (
        "Fixture fee schedule for widgets. Fictional."
    )


def test_decisions_carry_the_dmn_question(fixture_pack):
    questions = {d["attribute"]: d["question"] for d in fixture_pack["decisions"]}
    assert questions["fx:assessedFee"] == "What fee is assessed?"
    assert questions["fx:requiredMinimumScore"] == (
        "What minimum score must this widget meet?"
    )


def test_rule_order_is_document_order(fixture_pack):
    assert [r["id"] for r in fixture_pack["rules"]] == [
        "FXD-MINIMUM-01", "FXD-MINIMUM-02", "FXD-FEE-01", "FXD-FEE-00"
    ]


def test_column_whose_curie_another_decision_concludes_binds_as_derived(fixture_pack):
    fee = rule(fixture_pack, "FXD-FEE-01")
    assert fee["given"]["minimum"] == {"derived": "fx:requiredMinimumScore"}
    assert fee["given"]["score"] == {"attribute": "fx:score"}


def test_irrelevant_cell_does_not_bind_its_column(fixture_pack):
    """The whole-row `-` default binds nothing but the entity: binding the
    columns anyway would turn a presumption into a conditional."""
    default = rule(fixture_pack, "FXD-FEE-00")
    assert default["given"] == {"widget": {"entityType": "fx:Widget"}}
    assert "when" not in default


def test_irrelevant_cell_still_binds_when_another_cell_names_it(fixture_pack):
    """`minimum` has a `-` cell but is named by `< minimum`, so it must bind —
    and it must contribute no guard of its own."""
    fee = rule(fixture_pack, "FXD-FEE-01")
    assert fee["given"]["minimum"] == {"derived": "fx:requiredMinimumScore"}
    assert fee["when"] == ["score < minimum"]
    assert not [c for c in fee["when"] if c.startswith("minimum")]


def test_first_becomes_descending_priorities_in_row_order(fixture_pack):
    assert rule(fixture_pack, "FXD-FEE-01")["priority"] == 100
    assert rule(fixture_pack, "FXD-FEE-00")["priority"] == 0


def test_unique_puts_every_row_at_one_priority(fixture_pack):
    assert rule(fixture_pack, "FXD-MINIMUM-01")["priority"] == 0
    assert rule(fixture_pack, "FXD-MINIMUM-02")["priority"] == 0


def test_money_literal_keeps_its_exact_amount(fixture_pack):
    assert rule(fixture_pack, "FXD-FEE-00")["then"]["value"] == {
        "kind": "money", "amount": "0.00", "currency": "USD"
    }
    assert rule(fixture_pack, "FXD-FEE-01")["then"]["value"]["amount"] == "250.00"


def test_citation_carries_the_annotated_text(fixture_pack):
    assert rule(fixture_pack, "FXD-FEE-00")["citation"] == {
        "text": "Fixture fee schedule, default (fictional)"
    }


def test_rule_description_comes_from_the_dmn_description_element(fixture_pack):
    assert rule(fixture_pack, "FXD-FEE-00")["description"].startswith(
        "Otherwise nothing is owed"
    )


def test_supplying_the_pinned_ontology_changes_nothing_on_a_clean_document(fixture_pack):
    """`value_kinds` only ever adds refusals. On a document whose cells agree
    with the vocabulary it pins, the compilation must be identical — and the
    mapping must actually cover the attributes the document binds, or this
    would pass with an empty dict and prove nothing."""
    kinds = fixture_value_kinds()
    assert {"fx:score", "fx:category", "fx:requiredMinimumScore"} <= set(kinds)
    assert compile_file(FIXTURE_DMN, kinds) == fixture_pack


# --- smaller shapes --------------------------------------------------------
#
# Three conclusion shapes the fixture table deliberately does not have. It is
# two decisions wide on purpose — the studio's grid asserts its rule count —
# so the shapes it omits are exercised on the synthetic minimal document
# instead of being grown into it.


def _two_amount_columns(source: str) -> str:
    """Add two numeric input columns (and their `-` cells) to the minimal table,
    so an output *expression* has operands to name."""
    return source.replace(
        '<output id="o1" label="compliant" typeRef="boolean"/>',
        '<input id="i2" label="actual">'
        '<inputExpression typeRef="number"><text>nc:actualAmount</text></inputExpression>'
        "</input>"
        '<input id="i3" label="disclosed">'
        '<inputExpression typeRef="number"><text>nc:disclosedAmount</text></inputExpression>'
        "</input>"
        '<output id="o1" label="cure" typeRef="number"/>',
    ).replace(
        "<outputEntry>",
        "<inputEntry><text>-</text></inputEntry>"
        "<inputEntry><text>-</text></inputEntry><outputEntry>",
    )


def test_money_expression_carries_its_currency():
    """A computed money conclusion has no amount to read a currency from, so
    the currency comes off the decision — dropping it would emit an amount
    with no unit."""
    source = _two_amount_columns(minimal_dmn(output="actual - disclosed")).replace(
        'valueKind="boolean"', 'valueKind="money" currency="USD"'
    )
    assert compile_source(source)["rules"][0]["then"]["value"] == {
        "kind": "money", "currency": "USD", "expr": "actual - disclosed"
    }


def test_code_conclusion_carries_its_code_system():
    """A code is a value *in a system*: the bare string would be ambiguous
    between two vocabularies that spell a category the same way."""
    source = minimal_dmn(output='"Compliant"').replace(
        'valueKind="boolean"',
        'valueKind="code" codeSystem="fixture/statuses" codeSystemVersion="0.1.0"',
    )
    assert compile_source(source)["rules"][0]["then"]["value"] == {
        "kind": "code",
        "value": "Compliant",
        "codeSystem": "fixture/statuses",
        "codeSystemVersion": "0.1.0",
    }


def test_citation_url_is_optional_and_omitted_when_blank():
    """A blank `duly:citationUrl` cell must leave the key out rather than emit
    an empty string: `url: ""` is a citation claiming a source at no address."""
    with_column = minimal_dmn().replace(
        '<annotation name="duly:citation"/>',
        '<annotation name="duly:citation"/><annotation name="duly:citationUrl"/>',
    ).replace(
        "<annotationEntry><text>N.Y. Ins. Law &#167; 3425(d)(1)</text></annotationEntry>",
        "<annotationEntry><text>N.Y. Ins. Law &#167; 3425(d)(1)</text></annotationEntry>"
        "<annotationEntry><text>https://example.invalid/3425</text></annotationEntry>",
    )
    cited = compile_source(with_column)["rules"][0]["citation"]
    assert cited["url"] == "https://example.invalid/3425"

    blank = with_column.replace("<text>https://example.invalid/3425</text>", "<text></text>")
    assert compile_source(blank)["rules"][0]["citation"] == {"text": cited["text"]}

    # No column at all is the same answer as a blank one.
    assert "url" not in compile_source(minimal_dmn())["rules"][0]["citation"]


def test_minimal_document_compiles():
    pack = compile_source(minimal_dmn())
    assert pack["rules"][0]["then"]["value"] == {"kind": "boolean", "value": True}
    assert pack["rules"][0]["given"]["terminationNotice"] == {"entityType": "nc:TerminationNotice"}


def test_entity_variable_defaults_to_the_lowercased_local_name():
    pack = compile_source(minimal_dmn())
    assert pack["rules"][0]["then"]["entity"] == "terminationNotice"


def test_column_label_defaults_to_the_curie_local_part():
    source = minimal_dmn().replace(' label="state"', "")
    pack = compile_source(source)
    assert "governingState" in pack["rules"][0]["given"]


@pytest.mark.parametrize("policy", ["U", "F", "P"])
def test_single_letter_hit_policies_are_accepted(policy):
    compile_source(minimal_dmn(hit_policy=policy))


def test_rule_version_defaults_and_can_be_annotated():
    assert compile_source(minimal_dmn())["rules"][0]["version"] == "1.0.0"


def test_unknown_duly_annotation_is_refused_not_ignored():
    source = minimal_dmn().replace(
        '<annotation name="duly:citation"/>',
        '<annotation name="duly:citation"/><annotation name="duly:citaton"/>',
    ).replace(
        "<annotationEntry><text>1986-01-01</text></annotationEntry>",
        "<annotationEntry><text>oops</text></annotationEntry>"
        "<annotationEntry><text>1986-01-01</text></annotationEntry>",
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "duly:citaton" in str(excinfo.value)


def test_non_duly_annotation_columns_are_free_form():
    source = minimal_dmn().replace(
        '<annotation name="duly:ruleId"/>',
        '<annotation name="Comment"/><annotation name="duly:ruleId"/>',
    ).replace(
        "<annotationEntry><text>T-01</text></annotationEntry>",
        "<annotationEntry><text>reviewed by counsel 2026-01</text></annotationEntry>"
        "<annotationEntry><text>T-01</text></annotationEntry>",
    )
    assert compile_source(source)["rules"][0]["id"] == "T-01"


def test_bad_effective_date_is_refused():
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(minimal_dmn(effective_from="1st Jan 1986"))
    assert "ISO calendar date" in str(excinfo.value)


def test_boolean_valuekind_rejects_a_string_output_cell():
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(minimal_dmn(output='"yes"'))
    assert "`boolean` conclusion needs `true` or `false`" in str(excinfo.value)


def test_money_conclusion_without_a_currency_is_refused():
    source = minimal_dmn(output="0.00").replace('valueKind="boolean"', 'valueKind="money"')
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "needs `currency`" in str(excinfo.value)


def test_computed_code_conclusion_is_refused():
    source = minimal_dmn(output="state").replace(
        'valueKind="boolean"',
        'valueKind="code" codeSystem="x/y"',
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "no way to construct a code value" in str(excinfo.value)


def test_column_label_colliding_with_the_entity_variable_is_refused():
    source = minimal_dmn().replace('label="state"', 'label="terminationNotice"')
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert excinfo.value.klass == "binding-error"
    assert "collides with the entity binding" in str(excinfo.value)


def test_reserved_expression_name_as_a_column_label_is_refused():
    source = minimal_dmn().replace('label="state"', 'label="min"')
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "reserved in the duly expression language" in str(excinfo.value)


def test_duplicate_rule_ids_are_refused():
    source = minimal_dmn().replace(
        "</decisionTable>",
        """<rule id="r2">
             <inputEntry><text>"US-FL"</text></inputEntry>
             <outputEntry><text>false</text></outputEntry>
             <annotationEntry><text>T-01</text></annotationEntry>
             <annotationEntry><text>Fla. Stat. 627.4133</text></annotationEntry>
             <annotationEntry><text>1986-01-01</text></annotationEntry>
           </rule></decisionTable>""",
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "declared twice" in str(excinfo.value)


def test_unique_rows_scoped_by_string_equality_compile():
    """The one disjointness proof the kernel accepts."""
    source = minimal_dmn().replace(
        "</decisionTable>",
        """<rule id="r2">
             <inputEntry><text>"US-FL"</text></inputEntry>
             <outputEntry><text>false</text></outputEntry>
             <annotationEntry><text>T-02</text></annotationEntry>
             <annotationEntry><text>Fla. Stat. 627.4133</text></annotationEntry>
             <annotationEntry><text>1986-01-01</text></annotationEntry>
           </rule></decisionTable>""",
    )
    pack = compile_source(source)
    assert [r["priority"] for r in pack["rules"]] == [0, 0]


def test_unique_rows_with_disjoint_effective_windows_compile():
    source = minimal_dmn().replace(
        '<annotation name="duly:effectiveFrom"/>',
        '<annotation name="duly:effectiveFrom"/><annotation name="duly:effectiveTo"/>',
    ).replace(
        "<annotationEntry><text>1986-01-01</text></annotationEntry>",
        "<annotationEntry><text>1986-01-01</text></annotationEntry>"
        "<annotationEntry><text>2020-01-01</text></annotationEntry>",
    ).replace(
        "</decisionTable>",
        """<rule id="r2">
             <inputEntry><text>[1..5]</text></inputEntry>
             <outputEntry><text>false</text></outputEntry>
             <annotationEntry><text>T-02</text></annotationEntry>
             <annotationEntry><text>N.Y. Ins. Law 3425</text></annotationEntry>
             <annotationEntry><text>2020-01-01</text></annotationEntry>
             <annotationEntry><text></text></annotationEntry>
           </rule></decisionTable>""",
    )
    pack = compile_source(source)
    assert pack["rules"][0]["effectiveTo"] == "2020-01-01"


def test_priority_with_output_values_is_refused_rather_than_guessed():
    """DMN's PRIORITY orders by outputValues position, not row position."""
    source = minimal_dmn(hit_policy="PRIORITY").replace(
        '<output id="o1" label="compliant" typeRef="boolean"/>',
        '<output id="o1" label="compliant" typeRef="boolean">'
        "<outputValues><text>false,true</text></outputValues></output>",
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert excinfo.value.klass == "unsupported-hit-policy"
    assert "outputValues" in str(excinfo.value)


def test_dmn_12_namespace_is_refused_with_the_accepted_list():
    source = minimal_dmn(ns="http://www.omg.org/spec/DMN/20180521/MODEL/")
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert excinfo.value.klass == "unsupported-dmn-version"
    assert "20191111" in str(excinfo.value)


def test_boxed_expression_decision_is_refused():
    source = minimal_dmn()
    start = source.index("<decisionTable")
    end = source.index("</decisionTable>") + len("</decisionTable>")
    source = source[:start] + "<literalExpression><text>true</text></literalExpression>" + source[end:]
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert "decisionTable" in str(excinfo.value)


# --- refusal classes -------------------------------------------------------
#
# A compiler's refusals are half its contract. `test_refusals.py` asserts the
# message *prose* over the committed refusal examples, which are teaching
# content; these assert that the class fires at all, on documents this suite
# owns. They are the coverage that survives the examples' relocation, so they
# assert `klass` — the taxonomy — rather than wording.


def test_a_row_with_no_effective_date_is_refused():
    """Rule selection is effective-dated; a default start date would be a
    claim about legal history that nobody made."""
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(minimal_dmn(effective_from=""))
    assert excinfo.value.klass == "missing-effective-date"


def test_unique_rows_whose_disjointness_cannot_be_proven_are_refused():
    """Numeric ranges look exclusive to a human and are not a proof the kernel
    accepts. Emitting pairwise `overrides` would assert an ordering UNIQUE
    explicitly disclaims."""
    source = minimal_dmn(cell="[0..10]").replace(
        "</decisionTable>",
        """<rule id="r2">
             <inputEntry><text>&gt; 10</text></inputEntry>
             <outputEntry><text>false</text></outputEntry>
             <annotationEntry><text>T-02</text></annotationEntry>
             <annotationEntry><text>N.Y. Ins. Law 3425</text></annotationEntry>
             <annotationEntry><text>1986-01-01</text></annotationEntry>
           </rule></decisionTable>""",
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert excinfo.value.klass == "unprovable-unique"
    assert "FIRST" in str(excinfo.value), "the refusal must name the policy that means ordering"


def test_a_table_with_two_output_columns_is_refused():
    """A duly rule concludes exactly one attribute for one entity. Splitting a
    multi-output table would invent rules — with ids — the author never wrote."""
    source = minimal_dmn().replace(
        '<output id="o1" label="compliant" typeRef="boolean"/>',
        '<output id="o1" label="compliant" typeRef="boolean"/>'
        '<output id="o2" label="cure" typeRef="number"/>',
    ).replace(
        "<outputEntry><text>true</text></outputEntry>",
        "<outputEntry><text>true</text></outputEntry>"
        "<outputEntry><text>0.00</text></outputEntry>",
    )
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source)
    assert excinfo.value.klass == "unsupported-table-shape"
    assert "2 output columns" in str(excinfo.value)


def test_a_money_column_tested_against_a_bare_number_is_refused():
    """The one defect the compiler cannot reach from the DMN alone: valid
    S-FEEL, valid duly source, accepted by `validate_pack`, and fatal at
    adjudication. Catching it needs the attribute's value kind, so it is only
    refused when a caller supplies one.

    The mapping is stated inline rather than loaded from `fixtures/ontology/`
    because the fixture vocabulary declares no money-kind slot — and inline is
    the shape the compiler's API actually takes.
    """
    source = minimal_dmn(cell="&gt; 200")
    with pytest.raises(DmnCompileError) as excinfo:
        compile_source(source, {"nc:governingState": "money"})
    assert excinfo.value.klass == "unsupported-expression"
    assert "no money literal" in str(excinfo.value)

    # Without the mapping the same cell compiles: the refusal is the caller's
    # to enable, and this proves the test above is not passing for some other
    # reason.
    assert compile_source(source)["rules"][0]["when"] == ["state > 200"]


def test_the_fixture_refusal_names_its_row_and_rule():
    """The toolkit's own refusal input, compiled through the file path the
    studio uses. A refusal that cannot say *where* costs the author a hunt
    through XML."""
    with pytest.raises(DmnCompileError) as excinfo:
        compile_file(FIXTURE_REFUSALS / "uncited-row.dmn")
    assert excinfo.value.klass == "missing-citation"
    message = str(excinfo.value)
    for fragment in ("duly:citation", "row 2", "FXR-MINIMUM-02", "TODO(verify)"):
        assert fragment in message, f"refusal does not mention {fragment!r}"
