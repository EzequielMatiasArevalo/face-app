from __future__ import annotations

from typing import Protocol

from lib.schemas import EmbeddingRecord


class EmbeddingStoreProtocol(Protocol):
    def all(self) -> list[EmbeddingRecord]:
        ...

    def append(self, record: EmbeddingRecord) -> None:
        ...

    def delete_label(self, etiqueta: str) -> list[EmbeddingRecord]:
        """Borra todos los embeddings de una identidad y devuelve los registros borrados."""
        ...
