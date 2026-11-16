"""Scraper especializado para a plataforma Workable (apply.workable.com)."""

import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class WorkableScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        return "workable.com" in url.lower()

    def extract_job(self, url: str) -> Optional[Job]:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Título da vaga
            title_el = soup.select_one("h1, [data-ui='job-title']")
            title = title_el.get_text(strip=True) if title_el else "Vaga Sem Título"

            # Nome da empresa
            company = "Workable Company"
            company_match = re.search(r"workable\.com/([^/]+)", url)
            if company_match:
                raw = company_match.group(1)
                if raw not in ("j", "o"):
                    company = raw.replace("-", " ").title()

            company_el = soup.select_one("[data-ui='company-name'], .company")
            if company_el:
                company = company_el.get_text(strip=True)

            # Localização
            location_el = soup.select_one("[data-ui='job-location'], .location")
            location = location_el.get_text(strip=True) if location_el else "Não especificado"

            workplace_type = "Remoto" if "remot" in (title + " " + location).lower() else "Não especificado"

            # Descrição do corpo da vaga
            desc_el = soup.select_one("[data-ui='job-description'], .job-description, main, article")
            if desc_el:
                for tag in desc_el(["script", "style"]):
                    tag.decompose()
                description = desc_el.get_text(separator="\n", strip=True)
            else:
                description = soup.get_text(separator="\n", strip=True)

            return Job(
                title=title,
                company=company,
                url=url,
                platform="workable",
                location=location,
                workplace_type=workplace_type,
                description=description[:8000],
            )
        except Exception:
            return None
