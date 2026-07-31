"""The orientation strip: one guide per page, one page per guide.

The strip exists because every page opens onto three panes of vocabulary a
newcomer has no way into. That only holds if a new page gets one too — so the
binding between `data-guide` keys in the HTML and entries in guide.js is
asserted in both directions, and a page added without a guide fails here rather
than shipping as the one page with no way in.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
GUIDE_JS = STATIC / "guide.js"

# Every page the demo serves. Adding one without a guide is the failure this
# module is here to catch, so the list is the pages, not the pages-with-guides.
PAGES = ["index.html", "rules.html", "evidence.html", "receipt.html"]


def _page_key(name):
    """The `data-guide` key a page declares, or None."""
    html = (STATIC / name).read_text(encoding="utf-8")
    found = re.search(r'id="guide"[^>]*\bdata-guide="([a-z]+)"', html)
    return found.group(1) if found else None


def _guides():
    """The GUIDES literal in guide.js, as {key: [step source, ...]}."""
    source = GUIDE_JS.read_text(encoding="utf-8")
    body = source[source.index("const GUIDES = {"):source.index("const STORE_PREFIX")]
    blocks = re.split(r"^    ([a-z]+): \[$", body, flags=re.MULTILINE)[1:]
    return {
        key: re.findall(r'^      "', block, re.MULTILINE)
        for key, block in zip(blocks[::2], blocks[1::2])
    }


def _guide_keys():
    return set(_guides())


@pytest.mark.parametrize("name", PAGES)
def test_every_page_carries_a_guide(name):
    key = _page_key(name)
    assert key is not None, f"{name} has no #guide container"
    assert key in _guide_keys(), f"{name} declares data-guide={key!r}, guide.js has no such entry"


@pytest.mark.parametrize("name", PAGES)
def test_every_page_loads_the_guide_script_before_its_own(name):
    """guide.js reads `.workspace-intro` to attach the re-open control, so it
    has to run against a parsed document; and the page script must not have
    replaced the container first."""
    html = (STATIC / name).read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="/([a-z.]+\.js)"></script>', html)
    assert "guide.js" in scripts, f"{name} does not load guide.js"
    assert scripts.index("guide.js") == 0, f"{name} loads guide.js after its page script"


def test_no_guide_is_orphaned():
    """A guide nobody shows is copy that will rot unnoticed."""
    declared = {_page_key(name) for name in PAGES} - {None}
    assert _guide_keys() == declared


@pytest.mark.parametrize("name", PAGES)
def test_the_strip_ships_empty_and_hidden(name):
    """The container is filled by guide.js, so the copy has exactly one home.
    It also ships `hidden`: a strip that flashed on every load before the
    script could dismiss it would be worse than no strip at all."""
    html = (STATIC / name).read_text(encoding="utf-8")
    found = re.search(r'(<section class="guide"[^>]*>)(.*?)</section>', html, re.DOTALL)
    assert found, f"{name} has no guide section"
    assert "hidden" in found.group(1), f"{name}'s guide strip does not ship hidden"
    assert found.group(2).strip() == "", f"{name} inlines guide copy instead of keying it"


def test_every_guide_is_exactly_three_steps():
    """Three is the shape: fewer reads as an incomplete thought, more is the
    wall of text the strip exists to avoid. There is deliberately no lead line
    — each page already carries an h1 and a subtitle an inch above the strip,
    so a third piece of prose could only restate one of them."""
    guides = _guides()
    assert guides, "GUIDES did not parse"
    for key, steps in guides.items():
        assert len(steps) == 3, f"guide {key} has {len(steps)} steps, expected 3"
    assert "lead:" not in GUIDE_JS.read_text(encoding="utf-8")


def test_the_guide_never_reaches_for_innerhtml():
    """Demo discipline: no innerHTML anywhere. The copy is static rather than
    server data, but the rule is uniform so it stays easy to audit."""
    source = GUIDE_JS.read_text(encoding="utf-8")
    # Property access, not the bare word: the module's own header comment says
    # "No innerHTML anywhere", and a test that forbids saying so would be a
    # test against documenting the rule.
    for sink in (".innerHTML", ".outerHTML", ".insertAdjacentHTML"):
        assert sink not in source, f"guide.js reaches for {sink}"
