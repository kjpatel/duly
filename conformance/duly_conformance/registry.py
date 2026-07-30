"""Ontology registry: the caller-supplied set of (name, version) artifacts.

Library code takes a registry, never a repo path — a deployment's
ontologies live wherever that deployment keeps them. ``load_repo_registry``
is the convenience loader for this repo's layout
(``ontologies/<name>/<version>.yaml``), used by spec/validate.py, the CLI
default, and the tests.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .linkml_subset import Ontology, OntologySubsetError, parse_ontology

__all__ = ["OntologyRegistry", "load_repo_registry"]


class OntologyRegistry:
    """Version-pinned lookup of parsed ontologies."""

    def __init__(self, ontologies: list[Ontology] | None = None):
        self._by_ref: dict[tuple[str, str], Ontology] = {}
        for ontology in ontologies or []:
            self.add(ontology)

    def add(self, ontology: Ontology) -> None:
        key = (ontology.name, ontology.version)
        if key in self._by_ref:
            raise OntologySubsetError(f"duplicate ontology {ontology.ref}")
        self._by_ref[key] = ontology

    def get(self, name: str, version: str) -> Ontology | None:
        """Exact-pin lookup: version matching is equality, nothing looser."""
        return self._by_ref.get((name, version))

    def refs(self) -> list[str]:
        return sorted(o.ref for o in self._by_ref.values())

    def __len__(self) -> int:
        return len(self._by_ref)

    def __iter__(self):
        return iter(self._by_ref.values())


def load_repo_registry(ontologies_dir: str | Path) -> OntologyRegistry:
    """Load every ``<name>/<version>.yaml`` under ``ontologies_dir``.

    The directory and file names are checked against the document's own
    ``name``/``version`` — a mismatch is a load error, because the path is
    what a reader browses and the document is what the gate enforces, and
    they must not diverge.
    """
    root = Path(ontologies_dir)
    registry = OntologyRegistry()
    paths = sorted(root.glob("*/*.yaml"))
    if not paths:
        raise OntologySubsetError(f"no ontology files found under {root}")
    for path in paths:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        ontology = parse_ontology(doc)
        if ontology.name != path.parent.name or ontology.version != path.stem:
            raise OntologySubsetError(
                f"{path}: document says {ontology.ref}, path says "
                f"{path.parent.name}@{path.stem}"
            )
        registry.add(ontology)
    return registry
