"""Scraper especializado para a plataforma Gupy (*.gupy.io)."""

import json
import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class GupyScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        return "gupy.io" in url.lower()

    def extract_job(self, url: str) -> Optional[Job]:
        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
            }
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, "html.parser")

            # Título da vaga
            title_el = (
                soup.select_one("h1[data-testid='job-title']")
                or soup.select_one("h1.job-title")
                or soup.select_one("h1")
            )
            title = title_el.get_text(strip=True) if title_el else "Vaga Sem Título"

            # Nome da empresa via subdomínio ou elemento
            company = "Gupy Company"
            company_match = re.search(r"([a-zA-Z0-9_-]+)\.gupy\.io", url)
            if company_match:
                company = company_match.group(1).replace("-", " ").title()

            company_el = soup.select_one("[data-testid='company-name'], .company-name")
            if company_el:
                company = company_el.get_text(strip=True)

            # Localização
            location_el = soup.select_one(
                "[data-testid='job-location'], .job-location, .location"
            )
            location = location_el.get_text(strip=True) if location_el else "Brasil"

            # Modalidade (Remoto, Híbrido, Presencial)
            workplace_type = "Não especificado"
            wp_el = soup.select_one("[data-testid='job-workplace'], .workplace-type")
            if wp_el:
                wp_text = wp_el.get_text(strip=True).lower()
                if "remoto" in wp_text or "remote" in wp_text:
                    workplace_type = "Remoto"
                elif "híbrido" in wp_text or "hybrid" in wp_text or "hibrido" in wp_text:
                    workplace_type = "Híbrido"
                else:
                    workplace_type = "Presencial"
            elif "remot" in (title + " " + location).lower():
                workplace_type = "Remoto"

            # Descrição do corpo da vaga
            desc_el = soup.select_one(
                "[data-testid='job-description'], .job-description, .description-container, article, main"
            )
            if desc_el:
                for tag in desc_el(["script", "style", "nav"]):
                    tag.decompose()
                description = desc_el.get_text(separator="\n", strip=True)
            else:
                description = soup.get_text(separator="\n", strip=True)

            # Tenta extrair dados estruturados de JSON-LD se houver
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "{}")
                    if data.get("@type") == "JobPosting":
                        title = data.get("title", title)
                        hiring_org = data.get("hiringOrganization", {})
                        if isinstance(hiring_org, dict) and hiring_org.get("name"):
                            company = hiring_org.get("name")
                        if data.get("description"):
                            raw_desc = BeautifulSoup(data.get("description"), "html.parser").get_text(separator="\n", strip=True)
                            if len(raw_desc) > len(description):
                                description = raw_desc
                except Exception:
                    continue

            return Job(
                title=title,
                company=company,
                url=url,
                platform="gupy",
                location=location,
                workplace_type=workplace_type,
                description=description[:8000],
            )
        except Exception:
            return None
