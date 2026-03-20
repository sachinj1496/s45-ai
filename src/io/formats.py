"""Pluggable file format handlers and registry (strategy + chain-of-responsibility)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class UnsupportedDocumentFormatError(ValueError):
    """Raised when no registered handler can read a file."""


class FileFormatHandler(ABC):
    """
    Strategy: one implementation per family of on-disk formats (plain text, PDF, …).
    Register new handlers with `FormatRegistry.register` to extend supported types
    without changing ingestion or routing code (open/closed).
    """

    @abstractmethod
    def can_read(self, path: Path) -> bool:
        """Return True if this handler should read the given path."""

    @abstractmethod
    def read_text(self, path: Path) -> str:
        """Return normalised text suitable for classification / extraction."""


class PlainTextFormatHandler(FileFormatHandler):
    """UTF-8 text and markdown as used by the current corpus."""

    _suffixes = frozenset({".txt", ".md"})

    def can_read(self, path: Path) -> bool:
        return path.suffix.lower() in self._suffixes

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")


class FormatRegistry:
    """
    Registry of format handlers; first matching handler wins (chain of responsibility).
    """

    def __init__(self, handlers: list[FileFormatHandler] | None = None) -> None:
        self._handlers: list[FileFormatHandler] = list(handlers or [PlainTextFormatHandler()])

    def register(self, handler: FileFormatHandler, *, first: bool = False) -> None:
        if first:
            self._handlers.insert(0, handler)
        else:
            self._handlers.append(handler)

    def is_supported(self, path: str | Path) -> bool:
        p = Path(path)
        return any(h.can_read(p) for h in self._handlers)

    def read(self, path: str | Path) -> str:
        p = Path(path)
        for h in self._handlers:
            if h.can_read(p):
                return h.read_text(p)
        raise UnsupportedDocumentFormatError(f"No handler for suffix {p.suffix!r}: {p}")


_default_registry: FormatRegistry | None = None


def get_default_format_registry() -> FormatRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = FormatRegistry()
    return _default_registry
