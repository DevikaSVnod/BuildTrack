"""Content extractor plugin interface — index-time intelligence (optional)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ExtractionInput:
    """Input for an extractor plugin at index/upload time."""

    content_type: str  # e.g. drawing, document
    file_bytes: bytes
    mime_type: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    """Structured output persisted by the host app (JSON columns, sidecars, etc.)."""

    text: str = ""
    structured: dict[str, Any] = field(default_factory=dict)
    sidecar_text: str = ""


class ContentExtractor(ABC):
    """
    Runs at index time to build searchable text + structured fields.

    Examples: drawing object inventory, document body text, sheet intel.
    """

    name: str = "base"
    content_types: tuple[str, ...] = ()

    @abstractmethod
    def supports(self, content_type: str) -> bool:
        ...

    @abstractmethod
    def extract(self, data: ExtractionInput) -> ExtractionResult:
        ...
