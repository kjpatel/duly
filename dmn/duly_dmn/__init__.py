"""DMN decision-table compiler (spec/dmn.md).

An authoring surface, not an engine. `spec/rule-ir.md` opens by saying the IR
is "the neutral middle format for rules: authoring surfaces (YAML today, DMN
later) compile into it" — this package is that later. A DMN 1.3+ decision
table goes in; a rule-IR `pack.yaml` comes out, validated by the kernel's own
pack validator before it is returned. Nothing downstream knows or cares that
a pack was compiled rather than typed: same IR, same kernel, same receipts.

Three properties are load-bearing:

- **It refuses.** Cells outside S-FEEL, hit policies duly cannot express, and
  rows with no citation or no effective date are compile errors that name the
  decision, the row, and the offending text. There is no lenient mode. A
  silently approximated rule is worse than no rule at all.
- **It is deterministic.** Same DMN bytes in, byte-identical `pack.yaml` out,
  forever. No wall clock, no set iteration, no dict-order dependence.
- **It adds no dependencies.** stdlib `xml.etree` and the kernel, nothing else.

Entry points: `compile_file`, `compile_source`, `compile_definitions`,
`emit_pack`, and the `python -m duly_dmn` CLI.
"""

from .compiler import (
    KNOWN_ANNOTATIONS,
    SUPPORTED_HIT_POLICIES,
    compile_definitions,
    compile_file,
    compile_source,
)
from .emit import emit_pack
from .errors import DmnCompileError, Location
from .reader import DMN_NAMESPACES, DULY_NS, read_file, read_string

__all__ = [
    "DmnCompileError",
    "Location",
    "compile_file",
    "compile_source",
    "compile_definitions",
    "emit_pack",
    "read_file",
    "read_string",
    "DMN_NAMESPACES",
    "DULY_NS",
    "KNOWN_ANNOTATIONS",
    "SUPPORTED_HIT_POLICIES",
]
