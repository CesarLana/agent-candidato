"""Caçador autônomo de vagas em segundo plano (Background Job Hunter).

Monitora novas vagas em intervalos regulares, calcula o Fit Score de cada uma
e notifica no Telegram ou pré-aplica automaticamente caso o score atinja a nota de corte.
"""

import time
from datetime import datetime
from typing import List, Optional
from rich.console import Console

from automation.applicant import JobApplicant
from core.config import load_candidate_profile
from core.database import get_job_by_url, save_job
from core.llm import LLMEngine
from core.models import CandidateProfile, Job
from core.resume_tailor import ResumeTailor
from notifications.telegram_bot import TelegramNotifier
from scrapers import (
    fetch_job_details,
    search_gupy_jobs,
    search_linkedin_jobs,
    search_remoteok_jobs,
    search_weworkremotely_jobs,
)

console = Console(force_terminal=True, legacy_windows=False)


class JobHunterDaemon:
    def __init__(self, profile: Optional[CandidateProfile] = None):
        self.profile = profile or load_candidate_profile()
        self.llm = LLMEngine()
        self.notifier = TelegramNotifier()
        self.tailor = ResumeTailor(self.profile, self.llm)

    def run_hunt_cycle(self, auto_apply: bool = False, headless: bool = True) -> List[Job]:
        """Executa um ciclo completo de varredura por novas vagas."""
        console.print(f"\n[bold cyan]⏰ [{datetime.now().strftime('%H:%M:%S')}] Iniciando ciclo do Caçador de Vagas...[/]")

        target_roles = self.profile.preferences.target_roles or [
            "Analista de Infraestrutura Jr.",
            "DevOps Jr.",
            "Analista de Suporte Jr.",
            "Cloud Engineer Jr.",
        ]
        is_remote = "Remoto" in self.profile.preferences.work_modalities
        min_score = self.profile.preferences.min_fit_score or 55

        found_qualified_jobs: List[Job] = []

        for role in target_roles[:6]:  # Varre até 6 cargos prioritários
            console.print(f"[cyan]Buscando vagas para:[/] [bold]{role}[/]...")

            discovered_jobs = []

            # 1. Busca no LinkedIn em São Paulo (Presencial e Híbrido)
            try:
                li_sp = search_linkedin_jobs(
                    keywords=role,
                    location="São Paulo",
                    remote_only=False,
                    max_results=10,
                )
                discovered_jobs.extend(li_sp)
            except Exception as e:
                console.print(f"  [dim]Aviso LinkedIn SP: {e}[/dim]")

            # 2. Se aberto a remoto, busca também no LinkedIn Remoto Brasil
            if is_remote:
                try:
                    li_remoto = search_linkedin_jobs(
                        keywords=role,
                        location="Brazil",
                        remote_only=True,
                        max_results=8,
                    )
                    discovered_jobs.extend(li_remoto)
                except Exception as e:
                    console.print(f"  [dim]Aviso LinkedIn Remoto: {e}[/dim]")

            # 3. Busca no portal oficial da Gupy
            try:
                gupy_results = search_gupy_jobs(term=role, max_results=10)
                discovered_jobs.extend(gupy_results)
            except Exception as e:
                console.print(f"  [dim]Aviso Gupy: {e}[/dim]")

            for raw_job in discovered_jobs:
                # 1. Verifica se já está no banco para evitar duplicidade
                existing = get_job_by_url(raw_job.url)
                if existing:
                    continue

                console.print(f"  • Nova vaga detectada: [yellow]{raw_job.title}[/] @ [bold]{raw_job.company}[/]")

                # 2. Tenta extrair detalhes completos da página
                full_job = fetch_job_details(raw_job.url) or raw_job

                # 3. Avalia o Fit com IA
                score, summary, matched, missing = self.llm.evaluate_fit(full_job, self.profile)
                full_job.fit_score = score
                full_job.fit_summary = summary
                full_job.skills_matched = matched
                full_job.skills_missing = missing

                # Salva a vaga no banco SQLite
                saved_job = save_job(full_job)

                console.print(f"    ↳ Fit Score: [bold]{score}%[/] ({summary[:60]}...)")

                # Se a nota for compatível
                if score >= min_score:
                    found_qualified_jobs.append(saved_job)

                    # Gera o currículo sob medida
                    custom_pdf = None
                    try:
                        custom_pdf = self.tailor.generate_tailored_pdf(saved_job)
                    except Exception:
                        pass

                    # Notifica no Telegram
                    if self.notifier.is_configured:
                        self.notifier.notify_job_found(saved_job, pdf_path=custom_pdf)

                    # Se o modo auto-apply estiver ativo, inicia o fluxo de candidatura
                    if auto_apply:
                        console.print(f"[bold green]    🚀 Auto-apply ativado para {saved_job.title}! Iniciando preenchimento...[/]")
                        applicant = JobApplicant(profile=self.profile, headless=headless, tailor_resume=True)
                        applicant.run_application(saved_job, auto_submit=False)

        # Se busca vagas remotas, também varre canais globais
        if is_remote:
            console.print("[cyan]Varrendo oportunidades remotas globais (WeWorkRemotely / RemoteOK)...[/]")
            global_candidates = search_weworkremotely_jobs(category="backend", max_results=5)
            for raw_job in global_candidates:
                if get_job_by_url(raw_job.url):
                    continue

                full_job = fetch_job_details(raw_job.url) or raw_job
                score, summary, matched, missing = self.llm.evaluate_fit(full_job, self.profile)
                full_job.fit_score = score
                full_job.fit_summary = summary
                full_job.skills_matched = matched
                full_job.skills_missing = missing
                saved_job = save_job(full_job)

                if score >= min_score:
                    found_qualified_jobs.append(saved_job)
                    if self.notifier.is_configured:
                        self.notifier.notify_job_found(saved_job)
                    console.print(f"  • [green]Oportunidade global qualificada:[/] [bold]{saved_job.title}[/] @ {saved_job.company} ({score}%)")

        console.print(
            f"[bold green]✓ Ciclo finalizado:[/] {len(found_qualified_jobs)} vagas qualificadas encontradas e registradas."
        )
        return found_qualified_jobs

    def start_loop(self, interval_hours: float = 4.0, auto_apply: bool = False, headless: bool = True):
        """Inicia o daemon de caça em loop contínuo."""
        console.print(
            f"[bold green]🛡️ Caçador Autônomo Ativado![/]\n"
            f"• Intervalo de varredura: [bold]{interval_hours} horas[/]\n"
            f"• Nota de corte mínima: [bold]{self.profile.preferences.min_fit_score}%[/]\n"
            f"• Auto-apply: [bold]{'Sim (com confirmação)' if auto_apply else 'Não (Apenas Notificar)'}[/]\n"
            f"• Notificações no celular (Telegram): [bold]{'Ativas' if self.notifier.is_configured else 'Desativadas'}[/]\n"
        )

        interval_seconds = int(interval_hours * 3600)

        while True:
            try:
                self.run_hunt_cycle(auto_apply=auto_apply, headless=headless)
            except Exception as e:
                console.print(f"[bold red]Erro durante ciclo do caçador:[/] {e}")

            console.print(f"[dim]Próxima varredura em {interval_hours} horas. Pressione Ctrl+C para encerrar.[/dim]\n")
            time.sleep(interval_seconds)
