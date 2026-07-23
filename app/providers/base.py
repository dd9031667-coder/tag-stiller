from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import AlbumMetadata


class ProviderError(RuntimeError):
    pass


class CasaMusicaProvider(ABC):
    @abstractmethod
    def fetch_album(self, source: str) -> AlbumMetadata:
        """Вернуть нормализованные метаданные альбома."""

