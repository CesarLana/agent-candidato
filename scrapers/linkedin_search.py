"""Buscador de vagas no LinkedIn via URL pública de pesquisa (sem necessidade de login).

Utiliza o endpoint público guest-facing do LinkedIn. Não viola termos de uso
nem necessita de credenciais ou cookies de sessão.
"""

from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job


def search_linkedin_jobs(
    keywords: str,
    location: str = "Brazil",
    remote_only: bool = False,
    max_results: int = 15,
) -> List[Job]:
    """Busca vagas públicas no LinkedIn.

    Args:
        keywords: Termos de pesquisa (ex: "Python Backend", "React Developer").
        location: Localidade (ex: "São Paulo", "Brazil").
        remote_only: Se True, filtra apenas oportunidades remotas.
        max_results: Quantidade máxima de vagas para retornar.

    Returns:
        Lista de instâncias Job com título, empresa, URL e local.
    """
    jobs: List[Job] = []

    base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params: Dict[str, str] = {
        "keywords": keywords,
        "location": location,
        "start": "0",
        "sortBy": "DD", # Vagas mais recentes primeiro
    }

    if remote_only:
        params["f_WT"] = "2" # Código 2 = Remoto no LinkedIn

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        resp = requests.get(base_url, params=params, headers=headers, timeout=15)
        if resp.status_code != 200:
            return jobs

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.select(".base-card, .job-search-card, li")

        for card in cards[:max_results]:
            try:
                title_el = card.select_one(
                    ".base-search-card__title, .job-search-card__title, h3"
                )
                company_el = card.select_one(
                    ".base-search-card__subtitle, .job-search-card__company-name, h4"
                )
                location_el = card.select_one(
                    ".job-search-card__location, .base-search-card__metadata span"
                )
                link_el = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                company = company_el.get_text(strip=True) if company_el else "Empresa no LinkedIn"
                loc = location_el.get_text(strip=True) if location_el else location
                href = link_el.get("href", "").split("?")[0]

                if not href.startswith("http"):
                    href = "https://www.linkedin.com" + href

                workplace_type = "Remoto" if remote_only or "remote" in loc.lower() or "remoto" in loc.lower() else "Não especificado"

                jobs.append(
                    Job(
                        title=title,
                        company=company,
                        url=href,
                        platform="linkedin",
                        location=loc,
                        workplace_type=workplace_type,
                        description="",
                    )
                )
            except Exception:
                continue

    except Exception:
        pass

    return jobs
