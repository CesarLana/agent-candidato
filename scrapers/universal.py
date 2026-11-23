"""Scraper universal para páginas genéricas de anúncio de vagas."""

from typing import Optional
from urllib.parse import unquote, urlparse
import requests
from bs4 import BeautifulSoup

from core.models import Job
from scrapers.base import BaseScraper


class UniversalScraper(BaseScraper):
    def can_handle(self, url: str) -> bool:
        return True # Fallback para qualquer URL válida

    def extract_job(self, url: str) -> Optional[Job]:
        try:
            if url.startswith("file:///"):
                file_path = unquote(url.replace("file:///", ""))
                with open(file_path, "r", encoding="utf-8") as f:
                    html_content = f.read()
            else:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
                resp = requests.get(url, headers=headers, timeout=15)
                if resp.status_code != 200:
                    return None
                html_content = resp.text

            soup = BeautifulSoup(html_content, "html.parser")

            # Remove tags irrelevantes
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()

            # Tenta encontrar título
            title = ""
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()
            elif soup.h1:
                title = soup.h1.get_text(strip=True)
            elif soup.title:
                title = soup.title.get_text(strip=True)
            else:
                title = "Vaga Sem Título"

            # Empresa via domínio ou meta
            parsed_url = urlparse(url)
            domain_parts = parsed_url.netloc.split(".")
            company = domain_parts[-2].capitalize() if len(domain_parts) >= 2 else "Empresa"

            # Tenta pegar área principal
            main_el = soup.find("main") or soup.find("article") or soup.find("div", {"id": "job-details"}) or soup.body
            description = main_el.get_text(separator="\n", strip=True) if main_el else soup.get_text(separator="\n", strip=True)

            workplace_type = "Remoto" if any(w in description.lower() for w in ["remoto", "remote"]) else "Não especificado"

            return Job(
                title=title[:120],
                company=company,
                url=url,
                platform="universal",
                location="A consultar",
                workplace_type=workplace_type,
                description=description[:8000],
            )
        except Exception:
            return None
