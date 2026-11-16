"""Scraper especializado para a plataforma Greenhouse (boards.greenhouse.io)."""

import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class GreenhouseScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        return "greenhouse.io" in url.lower()

    def extract_job(self, url: str) -> Optional[Job]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Título da vaga
            title_el = soup.select_one(".app-title, h1.job-title, #header .title, h1")
            title = title_el.get_text(strip=True) if title_el else "Vaga Sem Título"

            # Nome da empresa
            company = "Greenhouse Company"
            company_match = re.search(r"greenhouse\.io/([^/]+)", url)
            if company_match:
                company = company_match.group(1).replace("-", " ").title()

            company_el = soup.select_one(".company-name, .header-company, .org")
            if company_el:
                company = company_el.get_text(strip=True)

            # Localização
            location_el = soup.select_one(".location, .job-location")
            location = location_el.get_text(strip=True) if location_el else "Não especificado"

            # Modalidade (remoto/presencial)
            workplace_type = "Remoto" if "remot" in (title + " " + location).lower() else "Não especificado"

            # Descrição do corpo da vaga
            content_el = soup.select_one("#content, #main-content, .job-description, #content-inner")
            if content_el:
                # Remove elementos de script e style
                for tag in content_el(["script", "style"]):
                    tag.decompose()
                description = content_el.get_text(separator="\n", strip=True)
            else:
                description = soup.get_text(separator="\n", strip=True)

            return Job(
                title=title,
                company=company,
                url=url,
                platform="greenhouse",
                location=location,
                workplace_type=workplace_type,
                description=description[:8000],
            )
        except Exception as e:
            return None
