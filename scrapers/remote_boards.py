"""Agregador de vagas remotas de plataformas globais (RemoteOK e WeWorkRemotely).

Permite descobrir oportunidades de trabalho 100% remotas (nacionais e globais/USD)
utilizando endpoints públicos e feeds RSS oficiais sem necessidade de chave de API.
"""

import warnings
from typing import Dict, List, Optional
import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from core.models import Job

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


def search_remoteok_jobs(tag: str = "python", max_results: int = 15) -> List[Job]:
    """Busca vagas remotas na API pública oficial do RemoteOK."""
    jobs: List[Job] = []
    url = f"https://remoteok.com/api?tag={tag}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return jobs

        data = resp.json()
        # O primeiro item da lista do RemoteOK costuma ser termos legais/metadata
        items = [i for i in data if isinstance(i, dict) and i.get("id")]

        for item in items[:max_results]:
            position = item.get("position", "Remote Position")
            company = item.get("company", "RemoteOK Company")
            apply_url = item.get("url", "")
            location = item.get("location", "Worldwide / Remote")
            description = BeautifulSoup(item.get("description", ""), "html.parser").get_text(separator="\n", strip=True)

            tags = item.get("tags", [])
            tag_summary = f"Tags: {', '.join(tags)}" if tags else ""

            jobs.append(
                Job(
                    title=position,
                    company=company,
                    url=apply_url,
                    platform="remoteok",
                    location=location or "Remoto Global",
                    workplace_type="Remoto",
                    description=f"{tag_summary}\n\n{description[:6000]}",
                )
            )
    except Exception:
        pass

    return jobs


def search_weworkremotely_jobs(category: str = "backend", max_results: int = 15) -> List[Job]:
    """Busca vagas remotas através do feed RSS público do WeWorkRemotely."""
    jobs: List[Job] = []
    
    # Categorias comuns no WeWorkRemotely
    rss_map = {
        "backend": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "frontend": "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
        "fullstack": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "devops": "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
    }
    feed_url = rss_map.get(category.lower(), rss_map["backend"])

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }

    try:
        resp = requests.get(feed_url, headers=headers, timeout=15)
        if resp.status_code != 200:
            return jobs

        soup = BeautifulSoup(resp.content, "html.parser")
        items = soup.find_all("item")

        for item in items[:max_results]:
            title_text = item.title.text if item.title else "Vaga Remota"
            # Formato do título no WWR: "Company: Title"
            company = "WeWorkRemotely"
            title = title_text
            if ":" in title_text:
                parts = title_text.split(":", 1)
                company = parts[0].strip()
                title = parts[1].strip()

            guid_el = item.find("guid")
            link_el = item.find("link")
            link = ""
            if guid_el and guid_el.text:
                link = guid_el.text.strip()
            elif link_el:
                link = link_el.next_sibling.strip() if link_el.next_sibling else ""

            desc = BeautifulSoup(item.description.text if item.description else "", "html.parser").get_text(separator="\n", strip=True)

            jobs.append(
                Job(
                    title=title,
                    company=company,
                    url=link,
                    platform="weworkremotely",
                    location="Remoto Global",
                    workplace_type="Remoto",
                    description=desc[:6000],
                )
            )
    except Exception:
        pass

    return jobs
