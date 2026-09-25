"""In-memory workspace of the local, single-user app: the spectra the user has loaded."""

from __future__ import annotations

import itertools
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from swirl.core.spectrum import SpectralSet, Spectrum


@dataclass(frozen=True)
class Entry:
    id: str
    spectrum: Spectrum
    source: str


class Workspace:
    def __init__(self) -> None:
        self._entries: dict[str, Entry] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def add(self, spectra: Iterable[Spectrum], source: str) -> list[Entry]:
        with self._lock:
            added = [Entry(f"s{next(self._ids)}", s, source) for s in spectra]
            self._entries.update((e.id, e) for e in added)
        return added

    def entries(self) -> list[Entry]:
        with self._lock:
            return list(self._entries.values())

    def get(self, ids: Sequence[str]) -> list[Entry]:
        with self._lock:
            missing = [i for i in ids if i not in self._entries]
            if missing:
                raise KeyError(", ".join(missing))
            return [self._entries[i] for i in ids]

    def remove(self, entry_id: str) -> None:
        with self._lock:
            if self._entries.pop(entry_id, None) is None:
                raise KeyError(entry_id)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


def group_by_grid(entries: Sequence[Entry]) -> list[list[Entry]]:
    """Split entries into groups sharing one wavelength grid and quantity (input order kept)."""
    groups: dict[tuple[bytes, str], list[Entry]] = {}
    for e in entries:
        key = (e.spectrum.wavelength.tobytes(), e.spectrum.quantity.value)
        groups.setdefault(key, []).append(e)
    return list(groups.values())


def as_set(group: Sequence[Entry]) -> SpectralSet:
    return SpectralSet.from_spectra([e.spectrum for e in group])
