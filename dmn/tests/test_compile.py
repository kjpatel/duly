"""Compiling a DMN document into the rule IR: bindings, hit policies, values."""

from __future__ import annotations

import pytest

from duly_dmn import compile_file, compile_source
from duly_dmn.errors import DmnCompileError
from dmntest_helpers import TRID_DMN, minimal_dmn


@pytest.fixture(scope="module")
def trid_pack():
    return compile_file(TRID_DMN)


def rule(pack, rule_id):
    return next(r for r in pack["rules"] if r["id"] == rule_id)


def test_pack_metadata_comes_from_the_duly_extension(trid_pack):
    assert trid_pack["pack"]["name"] == "trid-fee-tolerance-dmn"
    assert trid_pack["pack"]["ontology"] == "duly-mortgage-closing"
    # `<description>` is native DMN; the compiler uses DMN's own vocabulary
    # wherever DMN has one.
    assert trid_pack["pack"]["description"].startswith("TRID (Reg Z)")


def test_decisions_carry_the_dmn_question(trid_pack):
    questions = {d["attribute"]: d["question"] for d in trid_pack["decisions"]}
    assert questions["trid:toleranceCureAmount"] == (
        "Does this fee increase require a tolerance cure?"
    )


def test_rule_order_is_document_order(trid_pack):
    assert [r["id"] for r in trid_pack["rules"]] == [
        "TRID-CAT-02", "TRID-ZT-01", "TRID-DEF-00"
    ]


def test_column_whose_curie_another_decision_concludes_binds_as_derived(trid_pack):
    zt = rule(trid_pack, "TRID-ZT-01")
    assert zt["given"]["category"] == {"derived": "trid:toleranceCategory"}
    assert zt["given"]["actual"] == {"attribute": "trid:actualAmountAtClosing"}


def test_irrelevant_cell_does_not_bind_its_column(trid_pack):
    """The whole-row `-` default binds nothing but the entity: binding the
    columns anyway would turn a presumption into a conditional."""
    assert rule(trid_pack, "TRID-DEF-00")["given"] == {"fee": {"entityType": "trid:Fee"}}
    assert "when" not in rule(trid_pack, "TRID-DEF-00")


def test_irrelevant_cell_still_binds_when_another_cell_names_it(trid_pack):
    """`disclosed` has a `-` cell but is named by `> disclosed` and by the
    output expression, so it must bind."""
    zt = rule(trid_pack, "TRID-ZT-01")
    assert zt["given"]["disclosed"] == {"attribute": "trid:disclosedAmountAtBaseline"}
    assert "disclosed" not in " ".join(
        c for c in zt["when"] if c.startswith("disclosed")
    )
    assert zt["when"] == ['category == "ZeroTolerance"', "actual > disclosed"]


def test_first_becomes_descending_priorities_in_row_order(trid_pack):
    assert rule(trid_pack, "TRID-ZT-01")["priority"] == 100
    assert rule(trid_pack, "TRID-DEF-00")["priority"] == 0


def test_unique_puts_every_row_at_one_priority(trid_pack):
    assert rule(trid_pack, "TRID-CAT-02")["priority"] == 0


def test_money_literal_keeps_its_exact_amount(trid_pack):
    assert rule(trid_pack, "TRID-DEF-00")["then"]["value"] == {
        "kind": "money", "amount": "0.00", "currency": "USD"
    }


def test_money_expression_carries_its_currency(trid_pack):
    assert rule(trid_pack, "TRID-ZT-01")["then"]["value"] == {
        "kind": "money", "currency": "USD", "expr": "actual - disclosed"
    }


def test_code_conclusion_carries_its_code_system(trid_pack):
    assert rule(trid_pack, "TRID-CAT-02")["then"]["value"] == {
        "kind": "code",
        "value": "ZeroTolerance",
        "codeSystem": "duly-starter-trid/tolerance-categories",
        "codeSystemVersion": "0.1.0",
    }


def test_citation_url_is_optional_and_omitted_when_blank(trid_pack):
    assert rule(trid_pack, "TRID-DEF-00")["citation"] == {"text": "Default presumption"}
    assert "url" in rule(trid_pack, "TRID-CAT-02")["citation"]


def test_rule_description_comes_from_the_dmn_description_element(trid_pack):
    assert rule(trid_pack, "TRID-DEF-00")["description"].startswith("No tolerance cure")


# --- smaller shapes --------------------------------------------------------


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
