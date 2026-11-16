"""Classe base para scrapers de páginas de carreiras e vagas."""

from abc import ABC, abstractmethod
from typing import Optional
from core.models import Job


class BaseScraper(ABC):
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Retorna True se o scraper sabe processar essa URL."""
        pass

    @abstractmethod
    def extract_job(self, url: str) -> Optional[Job]:
        """Extrai os dados da vaga e retorna um objeto Job."""
        pass
