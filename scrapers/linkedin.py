"""Scraper especializado para páginas de vagas do LinkedIn (via endpoint guest-facing)."""

import re
from typing import Optional
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class LinkedInScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        url_lower = url.lower()
        return "linkedin.com/jobs" in url_lower or "linkedin.com/jobs-guest" in url_lower

    def extract_job(self, url: str) -> Optional[Job]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # Extrai o ID da vaga da URL
        job_id_match = re.search(r"/jobs/view/(\d+)", url) or re.search(r"currentJobId=(\d+)", url) or re.search(r"/jobPosting/(\d+)", url)
        
        html_content = ""
        if job_id_match:
            job_id = job_id_match.group(1)
            api_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
            try:
                resp = requests.get(api_url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    html_content = resp.text
            except Exception:
                pass

        if not html_content:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code == 200:
                    html_content = resp.text
            except Exception:
                return None

        if not html_content:
            return None

        soup = BeautifulSoup(html_content, "html.parser")

        # Título
        title_el = (
            soup.select_one("h2.top-card-layout__title")
            or soup.select_one("h1.top-card-layout__title")
            or soup.select_one(".topcard__title")
            or soup.select_one("h1")
        )
        title = title_el.get_text(strip=True) if title_el else "Vaga no LinkedIn"

        # Empresa
        company_el = (
            soup.select_one("a.topcard__org-name-link")
            or soup.select_one(".topcard__flavor--black-link")
            or soup.select_one(".top-card-layout__first-sub-headline")
            or soup.select_one(".company-name")
        )
        company = company_el.get_text(strip=True) if company_el else "Empresa no LinkedIn"

        # Localização
        location_el = (
            soup.select_one(".topcard__flavor--bullet")
            or soup.select_one(".top-card-layout__second-sub-headline")
            or soup.select_one(".location")
        )
        location = location_el.get_text(strip=True) if location_el else "Brasil"

        # Descrição
        desc_el = (
            soup.select_one(".show-more-less-html__markup")
            or soup.select_one(".description__text")
            or soup.select_one("article")
            or soup.select_one("main")
        )
        if desc_el:
            for tag in desc_el(["script", "style"]):
                tag.decompose()
            description = desc_el.get_text(separator="\n", strip=True)
        else:
            description = soup.get_text(separator="\n", strip=True)

        # Modalidade
        workplace_type = "Não especificado"
        full_text_lower = (title + " " + location + " " + description[:500]).lower()
        if "remoto" in full_text_lower or "remote" in full_text_lower:
            workplace_type = "Remoto"
        elif "híbrido" in full_text_lower or "hybrid" in full_text_lower or "hibrido" in full_text_lower:
            workplace_type = "Híbrido"

        return Job(
            title=title,
            company=company,
            url=url,
            platform="linkedin",
            location=location,
            workplace_type=workplace_type,
            description=description[:8000],
        )
