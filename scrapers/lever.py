"""Scraper especializado para a plataforma Lever (jobs.lever.co)."""

import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class LeverScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        return "lever.co" in url.lower()

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
            title_el = soup.select_one(".posting-headline h2, h2")
            title = title_el.get_text(strip=True) if title_el else "Vaga Sem Título"

            # Nome da empresa
            company = "Lever Company"
            company_match = re.search(r"jobs\.lever\.co/([^/]+)", url)
            if company_match:
                company = company_match.group(1).replace("-", " ").title()

            # Categorias / Localização
            cats_el = soup.select_one(".posting-categories")
            location = "Não especificado"
            workplace_type = "Não especificado"
            if cats_el:
                location = cats_el.get_text(separator=" | ", strip=True)
                if "remote" in location.lower() or "remoto" in location.lower():
                    workplace_type = "Remoto"

            # Descrição do corpo da vaga
            desc_blocks = soup.select(".section-wrapper, .posting-page")
            description = ""
            for block in desc_blocks:
                for tag in block(["script", "style"]):
                    tag.decompose()
                description += block.get_text(separator="\n", strip=True) + "\n"

            if not description:
                description = soup.get_text(separator="\n", strip=True)

            return Job(
                title=title,
                company=company,
                url=url,
                platform="lever",
                location=location,
                workplace_type=workplace_type,
                description=description[:8000],
            )
        except Exception:
            return None
