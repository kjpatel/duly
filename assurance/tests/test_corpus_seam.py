"""The seams the three corpus commands share: pack resolution, and the registry.

Both exist because the same thing was written three ways. Pack resolution was
`parents[2]`-of-the-installed-package in `verify` and `generate` — the
repository only while duly runs from a checkout — and working-directory-first
in `impact`, which is the correct one and is now the only one.

The registry is the other half: the six packs, their vocabularies and the fact
builders that speak them are example content, and this is the seam that lets
them be registered from outside rather than hardcoded in a dispatch chain.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from duly_assurance.corpus import PackNotFound, resolve_pack_path
from duly_assurance.generate import (
    KINDS,
    STATE_TEMPLATES,
    register_kind,
    register_template,
)


# --- pack resolution --------------------------------------------------------


def test_an_absolute_path_is_taken_as_given(tmp_path):
    pack = tmp_path / "pack.yaml"
    pack.write_text("pack: {}")
    assert resolve_pack_path(str(pack), tmp_path) == pack


def test_a_relative_path_resolves_against_the_working_directory(tmp_path, monkeypatch):
    """What the author of `rulepacks/x/pack.yaml` meant by it."""
    (tmp_path / "rulepacks").mkdir()
    pack = tmp_path / "rulepacks" / "pack.yaml"
    pack.write_text("pack: {}")
    monkeypatch.chdir(tmp_path)
    assert resolve_pack_path("rulepacks/pack.yaml", tmp_path / "golden") == pack


def test_a_relative_path_also_resolves_beside_the_corpus(tmp_path, monkeypatch):
    """A corpus sitting next to its packs resolves without a `cd`."""
    project = tmp_path / "project"
    (project / "rulepacks").mkdir(parents=True)
    pack = project / "rulepacks" / "pack.yaml"
    pack.write_text("pack: {}")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert resolve_pack_path("rulepacks/pack.yaml", project / "golden") == pack


def test_a_missing_pack_names_every_candidate_tried(tmp_path, monkeypatch):
    """"pack not found" without the paths is the least actionable error a
    corpus run can produce."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PackNotFound) as excinfo:
        resolve_pack_path("rulepacks/nope.yaml", tmp_path / "golden")
    message = str(excinfo.value)
    assert "rulepacks/nope.yaml" in message
    assert message.count("tried") == 1
    assert str(tmp_path) in message


def test_resolution_does_not_consult_dulys_own_install_location(tmp_path, monkeypatch):
    """The defect this replaced: `parents[2]` of the installed package is the
    repository from a checkout and a site-packages directory from a wheel, so
    the same corpus resolved differently depending on how duly was installed."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(PackNotFound) as excinfo:
        resolve_pack_path("rulepacks/termination-notice-us-states/pack.yaml", tmp_path)
    # Only the two legitimate candidates were tried; duly's own tree — where
    # this path really does exist — was never one of them.
    tried = str(excinfo.value)
    assert str(tmp_path) in tried
    assert "duly_assurance" not in tried


# --- the template registry --------------------------------------------------


def test_the_six_built_in_kinds_are_registered():
    assert sorted(KINDS) == ["esign", "notice", "rec", "resc", "ron", "trid"]


def test_the_eight_built_in_templates_are_registered():
    assert set(STATE_TEMPLATES) == {"ny", "fl", "ca", "trid", "ron", "esign", "resc", "rec"}


def test_every_template_names_a_registered_kind():
    for name, template in STATE_TEMPLATES.items():
        assert template["kind"] in KINDS, name


def test_registering_a_kind_twice_is_refused():
    """Silent overwrite would make a corpus depend on import order."""
    with pytest.raises(ValueError, match="already registered"):
        register_kind("notice", draw=lambda t, r, i: {}, build=lambda **kw: [])


def test_registering_a_template_twice_is_refused():
    with pytest.raises(ValueError, match="already registered"):
        register_template("ny", dict(STATE_TEMPLATES["ny"]))


def test_a_template_naming_an_unknown_kind_is_refused_at_registration():
    """Not partway through a generation run, when some cases are already
    written."""
    with pytest.raises(ValueError, match="not registered"):
        register_template("bogus", {"kind": "no-such-kind", "weight": 1})


@pytest.mark.parametrize(
    "name,question",
    [
        ("ny", "nc:noticeCompliant"),
        ("trid", "trid:toleranceCureAmount"),
        ("ron", "ron:notarizationCompliant"),
        ("esign", "pkg:signingMethod"),
        ("resc", "resc:fundingPermitted"),
        ("rec", "rec:recordable"),
    ],
)
def test_each_templates_default_question_is_pinned(name, question):
    """Converting the template dict into registration calls is a transcription,
    and a transcription can be wrong in a way nothing else notices: a mistyped
    default question still generates 350 valid cases, just different ones. It
    was caught by regenerating and diffing, and these pin it cheaply."""
    assert STATE_TEMPLATES[name]["question"] == question
