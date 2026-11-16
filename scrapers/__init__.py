"""Módulo unificado de coleta de informações de vagas."""

from typing import List, Optional
from core.models import Job
from scrapers.base import BaseScraper
from scrapers.greenhouse import GreenhouseScraper
from scrapers.lever import LeverScraper
from scrapers.gupy import GupyScraper
from scrapers.workable import WorkableScraper
from scrapers.universal import UniversalScraper
from scrapers.linkedin_search import search_linkedin_jobs
from scrapers.remote_boards import search_remoteok_jobs, search_weworkremotely_jobs

SCRAPERS: List[BaseScraper] = [
    GreenhouseScraper(),
    LeverScraper(),
    GupyScraper(),
    WorkableScraper(),
    UniversalScraper(), # Sempre por último como fallback
]


def fetch_job_details(url: str) -> Optional[Job]:
    """Descobre o scraper apropriado e extrai as informações da vaga a partir da URL."""
    for scraper in SCRAPERS:
        if scraper.can_handle(url):
            job = scraper.extract_job(url)
            if job:
                return job
    return None


__all__ = [
    "BaseScraper",
    "GreenhouseScraper",
    "LeverScraper",
    "GupyScraper",
    "WorkableScraper",
    "UniversalScraper",
    "fetch_job_details",
    "search_linkedin_jobs",
    "search_remoteok_jobs",
    "search_weworkremotely_jobs",
]
