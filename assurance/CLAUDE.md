# Working on assurance/

Loaded alongside the root CLAUDE.md when work touches this directory.

- **`prove` only ever sees packs the kernel already blessed.** `validate_pack` refuses any same-priority pair concluding one attribute unless it can prove disjointness syntactically or the author wrote an `overrides` — so a pack with an *unproven* same-priority overlap cannot load, and `python -m duly_assurance prove` cannot meet one in a committed pack. Its non-zero exit is a **differential check between two proof systems**, not a routine gate: it firing would mean Z3 refuted a proof `_equality_guards` accepted. Don't write a test that reaches it through `load_pack` — build the pack dict and call `analyze_pack` directly.

- **`impact.analyze` takes `pack_overrides`; the CLI never passes it.** Keyed by *resolved* pack path, it seeds the pack cache so a candidate that exists only in memory is measured against the corpus slice it governs. Reading the working tree is the point of the command, so the flag is for callers holding a pack that is not (and may never be) a file — an impact number an author sees before writing the file is the only one that can change their mind.
