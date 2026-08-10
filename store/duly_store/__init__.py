"""duly bitemporal fact store: append-only events, as-of projections.

``FactStore`` is the package; it is re-exported here so first contact is
``from duly_store import FactStore`` rather than a tour of the file layout
(finding A1's lesson, applied at the store edge).
"""

from .store import (
    DuplicateFactError,
    FactStore,
    FactStoreError,
    HashMismatchError,
)

__all__ = [
    "DuplicateFactError",
    "FactStore",
    "FactStoreError",
    "HashMismatchError",
]
