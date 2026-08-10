# Working on whatif/

Loaded alongside the root CLAUDE.md when work touches this directory.

- **A what-if answer is a proposal until the kernel has run.** `whatif/` reuses `prove`'s SMT encoding unmodified but stands in the *opposite* relation to it: `prove` lives on UNSAT, where widening the input space is safe; what-if lives on SAT, where widening is exactly what makes an answer unreliable. So every value it returns is re-adjudicated through `duly_kernel.api.adjudicate`, and extremals are boundary-verified. Never add a return path that skips that — a spurious SAT must become a `SolverKernelContradiction`, not an answer. And never write a second encoder: `test_the_encoding_is_the_one_prove_uses` asserts class identity so divergence has to be deliberate.
