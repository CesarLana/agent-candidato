"""Interface de linha de comando (CLI) principal do Agente Candidato."""

import os
import sys
from pathlib import Path
from typing import Optional
import typer
from rich import print
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Configura UTF-8 no Windows para evitar UnicodeEncodeError em terminais legados
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Adiciona o diretório base ao sys.path para importações locais
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from automation.applicant import JobApplicant
from automation.safety_guard import SafetyGuard
from automation.session_manager import SessionManager, PLATFORMS
from automation.linkedin_applier import LinkedInApplier
from core.ats_scanner import ATSCompatibilityScanner
from core.config import get_profile_path, load_candidate_profile
from core.database import export_to_csv, get_stats, list_jobs, save_cover_letter, save_job
from core.interview_coach import InterviewCoach
from core.llm import LLMEngine
from core.models import Job
from core.networking import NetworkingCoach
from core.resume_tailor import ResumeTailor
from core.salary_advisor import SalaryAdvisor
from core.skill_roadmap import SkillGapRoadmap
from email_tracker.tracker import EmailFeedbackTracker
from notifications.telegram_bot import TelegramNotifier
from scheduler.hunter import JobHunterDaemon
from scrapers import (
    fetch_job_details,
    search_linkedin_jobs,
    search_remoteok_jobs,
    search_weworkremotely_jobs,
)

app = typer.Typer(
    help="🤖 Agente Inteligente de Candidatura a Vagas de Emprego",
    rich_markup_mode="rich",
)
console = Console(force_terminal=True, legacy_windows=False)


@app.command()
def setup():
    """Valida o perfil do candidato, configurações de IA e arquivo de currículo."""
    console.print(Panel.fit("[bold green]Diagnóstico e Configuração do Agente[/]", border_style="cyan"))

    profile_path = get_profile_path()
    console.print(f"[bold cyan]Arquivo de perfil:[/] {profile_path}")

    try:
        profile = load_candidate_profile()
        console.print(f"[green]✓[/] Perfil carregado para: [bold]{profile.personal_info.full_name or profile.personal_info.first_name}[/]")
        console.print(f"[green]✓[/] E-mail: {profile.personal_info.email}")
        console.print(f"[green]✓[/] Habilidades primárias: {', '.join(profile.skills.primary)}")
    except Exception as e:
        console.print(f"[red]✗ Erro ao carregar perfil:[/] {e}")
        return

    # Validação do currículo
    resume_path = BASE_DIR / profile.documents.resume_pdf_path
    if resume_path.exists():
        console.print(f"[green]✓[/] Arquivo de currículo encontrado: [bold]{resume_path.name}[/]")
    else:
        # Checa arquivos alternativos em data/
        alts = list((BASE_DIR / "data").glob("*.pdf")) + list((BASE_DIR / "data").glob("*.txt"))
        if alts:
            console.print(f"[yellow]![/] Currículo padrão '{profile.documents.resume_pdf_path}' não encontrado, mas arquivo alternativo detectado: [bold]{alts[0].name}[/]")
        else:
            console.print(f"[yellow]![/] Atenção: Nenhum currículo PDF/TXT encontrado na pasta data/. Adicione seu currículo para anexação automática.")

    # Status de IA
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if gemini_key:
        console.print("[green]✓[/] Motor de IA: [bold]Google Gemini[/] configurado.")
    elif openai_key:
        console.print("[green]✓[/] Motor de IA: [bold]OpenAI[/] configurado.")
    else:
        console.print("[yellow]![/] Chaves de IA não informadas no .env. O agente funcionará no [bold]Modo Heurístico Inteligente[/] (sem custos).")

    # Status do Telegram
    tele_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tele_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tele_token and tele_chat and tele_token != "seu_token_aqui":
        console.print("[green]✓[/] Notificações & Aprovação remota: [bold]Telegram Bot[/] ativo e configurado.")
    else:
        console.print("[dim]i Telegram Bot não configurado no .env (Aprovação será feita diretamente no terminal).[/dim]")


@app.command()
def apply(
    url: str = typer.Argument(..., help="URL completa da vaga (Greenhouse, Lever ou genérica)"),
    auto_submit: bool = typer.Option(False, "--auto-submit", help="Submete sem esperar confirmação humana (não recomendado)"),
    headless: bool = typer.Option(False, "--headless", help="Roda o navegador sem interface visível"),
    tailor: bool = typer.Option(True, "--tailor/--no-tailor", help="Gera currículo em PDF sob medida otimizado para o ATS da vaga"),
    force: bool = typer.Option(False, "--force", "-f", help="Aplica mesmo se a nota de corte mínima não for atingida"),
):
    """Analisa uma vaga pela URL, calcula o Fit Score e preenche a candidatura no navegador."""
    console.print(Panel.fit(f"[bold cyan]Processando Vaga:[/] {url}", border_style="blue"))

    profile = load_candidate_profile()
    llm = LLMEngine()

    with console.status("[bold green]Coletando dados da vaga..."):
        job = fetch_job_details(url)

    if not job:
        console.print("[bold red]Não foi possível extrair informações estruturadas desta página.[/]")
        return

    with console.status("[bold green]Analisando fit com seu perfil usando IA..."):
        score, summary, matched, missing = llm.evaluate_fit(job, profile)
        job.fit_score = score
        job.fit_summary = summary
        job.skills_matched = matched
        job.skills_missing = missing
        job = save_job(job)

    # Painel de Avaliação
    color = "green" if score >= 75 else ("yellow" if score >= 60 else "red")
    matched_str = ", ".join(matched) if matched else "Nenhuma detectada diretamente"
    missing_str = ", ".join(missing) if missing else "Nenhum gap crítico detectado"

    match_panel = f"""
[bold]Vaga:[/] {job.title}
[bold]Empresa:[/] {job.company}
[bold]Localização:[/] {job.location} ({job.workplace_type})
[bold]Fit Score:[/] [{color} bold]{score}/100[/{color} bold]

[bold green]✓ Skills Alinhadas:[/] {matched_str}
[bold yellow]! Gaps / A Desenvolver:[/] {missing_str}

[bold]Diagnóstico da IA:[/]
{summary}
"""
    console.print(Panel(match_panel, title="[bold]Análise de Compatibilidade[/]", border_style=color))

    # Verifica se atinge nota de corte configurada
    if score < profile.preferences.min_fit_score and not force:
        console.print(f"[yellow]Nota de corte ({profile.preferences.min_fit_score}) não atingida.[/]")
        proceed = console.input("[yellow]Deseja se candidatar mesmo assim? (s/n): [/]").strip().lower()
        if proceed not in ["s", "sim", "y"]:
            job.status = "skipped"
            job.notes = "Ignorada por baixo fit score."
            save_job(job)
            console.print("[dim]Candidatura ignorada.[/dim]")
            return

    # Inicia a automação de preenchimento
    applicant = JobApplicant(profile=profile, headless=headless, tailor_resume=tailor)
    applicant.run_application(job, auto_submit=auto_submit)


@app.command()
def search(
    keywords: str = typer.Argument(..., help="Termos da busca (ex: 'Desenvolvedor Python', 'React Remote')"),
    location: str = typer.Option("Brasil", "--location", "-l", help="Localidade da vaga"),
    remote: bool = typer.Option(True, "--remote/--all", help="Filtrar apenas vagas remotas"),
    limit: int = typer.Option(10, "--limit", "-n", help="Número de vagas a buscar"),
):
    """Busca vagas públicas no LinkedIn e permite avaliar/candidatar-se imediatamente."""
    console.print(Panel.fit(f"[bold cyan]🔍 Buscando vagas:[/] '{keywords}' em {location} {'(Remoto)' if remote else ''}", border_style="blue"))

    with console.status("[bold green]Consultando listagem de vagas..."):
        jobs = search_linkedin_jobs(keywords=keywords, location=location, remote_only=remote, max_results=limit)

    if not jobs:
        console.print("[yellow]Nenhuma vaga encontrada com esses critérios ou limite atingido.[/]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="center", width=4)
    table.add_column("Cargo", min_width=25)
    table.add_column("Empresa", min_width=15)
    table.add_column("Local", width=18)
    table.add_column("URL", width=35)

    for i, j in enumerate(jobs, 1):
        table.add_row(str(i), j.title, j.company, j.location[:17], j.url[:34] + "...")

    console.print(table)
    console.print("\n[dim]Dica: Copie a URL ou escolha o número de uma vaga para analisar e aplicar.[/dim]")

    choice = console.input("[bold green]Deseja analisar alguma dessas vagas agora? (Digite o número ou 'n'): [/]").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(jobs):
        chosen_job = jobs[int(choice) - 1]
        console.print(f"[cyan]Iniciando análise da vaga #{choice}:[/] {chosen_job.title}")
        apply(url=chosen_job.url)


@app.command(name="dashboard")
def dashboard_cmd(
    port: int = typer.Option(8000, "--port", "-p", help="Porta local para rodar o dashboard"),
    host: str = typer.Option("127.0.0.1", "--host", help="Host local"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Abre o navegador automaticamente"),
):
    """Inicia o Dashboard Visual Web interativo em seu navegador."""
    import webbrowser
    import uvicorn
    from web.app import app as web_app

    url = f"http://{host}:{port}"
    console.print(Panel.fit(
        f"[bold green]🚀 Dashboard Web Iniciado![/]\n"
        f"Acesse em seu navegador: [bold cyan]{url}[/]\n"
        f"[dim]Pressione Ctrl+C para encerrar o servidor.[/dim]",
        border_style="green",
    ))

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    uvicorn.run(web_app, host=host, port=port, log_level="warning")


@app.command(name="interview-prep")
def interview_prep_cmd(
    target: str = typer.Argument(..., help="ID da vaga no banco (ex: 1) ou URL da vaga"),
):
    """Gera um roteiro completo de preparação para entrevista com IA (Top perguntas, STAR e dicas)."""
    profile = load_candidate_profile()
    llm = LLMEngine()
    coach = InterviewCoach(profile, llm)

    job: Optional[Job] = None
    if target.isdigit():
        jobs = list_jobs()
        job = next((j for j in jobs if j.id == int(target)), None)
    else:
        job = fetch_job_details(target)

    if not job:
        console.print("[bold red]Vaga não encontrada no banco nem na URL informada.[/]")
        return

    console.print(Panel.fit(f"[bold cyan]Preparando Entrevista para:[/] {job.title} @ {job.company}", border_style="yellow"))

    with console.status("[bold green]Simulando perguntas técnicas e comportamentais com IA..."):
        guide = coach.generate_prep_guide(job)

    console.print(Panel(guide, title=f"🎯 Roteiro de Entrevista - {job.company}", border_style="green"))
    console.print("[dim]✓ Roteiro completo salvo em formato Markdown na pasta data/.[/dim]")


@app.command(name="remote-search")
def remote_search_cmd(
    tag: str = typer.Argument("python", help="Palavra-chave ou tecnologia (ex: python, react, devops)"),
    source: str = typer.Option("all", "--source", "-s", help="Fonte: remoteok, weworkremotely, ou all"),
    limit: int = typer.Option(10, "--limit", "-n", help="Número máximo de vagas"),
):
    """Busca vagas remotas globais nas plataformas RemoteOK e WeWorkRemotely."""
    console.print(Panel.fit(f"[bold cyan]🌐 Buscando Vagas Remotas Globais:[/] '{tag}'", border_style="blue"))

    jobs: List[Job] = []
    with console.status("[bold green]Consultando APIs e feeds remotos..."):
        if source in ["all", "remoteok"]:
            jobs.extend(search_remoteok_jobs(tag=tag, max_results=limit))
        if source in ["all", "weworkremotely"]:
            jobs.extend(search_weworkremotely_jobs(category=tag, max_results=limit))

    if not jobs:
        console.print("[yellow]Nenhuma vaga remota encontrada com esse termo.[/]")
        return

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", justify="center", width=4)
    table.add_column("Cargo", min_width=25)
    table.add_column("Empresa", min_width=15)
    table.add_column("Plataforma", width=15)
    table.add_column("URL", width=35)

    for i, j in enumerate(jobs[:limit], 1):
        table.add_row(str(i), j.title, j.company, f"[bold blue]{j.platform}[/]", j.url[:34] + "...")

    console.print(table)

    choice = console.input("\n[bold green]Deseja analisar alguma dessas vagas remotas agora? (Digite o número ou 'n'): [/]").strip()
    if choice.isdigit() and 1 <= int(choice) <= len(jobs):
        chosen = jobs[int(choice) - 1]
        apply(url=chosen.url)


@app.command(name="auto-hunt")
def auto_hunt_cmd(
    interval_hours: float = typer.Option(4.0, "--interval-hours", "-i", help="Intervalo entre as varreduras em horas"),
    once: bool = typer.Option(False, "--once", help="Executa apenas uma varredura imediatamente e encerra"),
    auto_apply: bool = typer.Option(False, "--auto-apply", help="Inicia o fluxo de candidatura para vagas acima da nota de corte"),
    headless: bool = typer.Option(True, "--headless/--visible", help="Executa o navegador em segundo plano"),
):
    """Ativa o Caçador Autônomo em segundo plano para monitorar novas vagas periodicamente."""
    daemon = JobHunterDaemon()
    if once:
        daemon.run_hunt_cycle(auto_apply=auto_apply, headless=headless)
    else:
        daemon.start_loop(interval_hours=interval_hours, auto_apply=auto_apply, headless=headless)


@app.command(name="track-emails")
def track_emails_cmd():
    """Varre a caixa de e-mail em busca de convites para entrevista e respostas de RH."""
    tracker = EmailFeedbackTracker()
    if not tracker.is_configured:
        console.print("[yellow]Para rastrear retornos de recrutadores por e-mail, configure EMAIL_USER e EMAIL_PASSWORD no .env.[/]")
        return
    tracker.sync_feedback()
    funnel_cmd()


@app.command(name="funnel")
def funnel_cmd():
    """Exibe o Funil de Conversão completo das candidaturas (Aplicadas -> Entrevistas -> Ofertas)."""
    jobs = list_jobs()
    total = len(jobs)
    applied = sum(1 for j in jobs if j.status == "applied")
    interviews = sum(1 for j in jobs if j.status == "interview")
    offers = sum(1 for j in jobs if j.status == "offer")
    rejected = sum(1 for j in jobs if j.status == "rejected")
    pending = sum(1 for j in jobs if j.status == "pending")

    rate = (interviews / applied * 100) if applied > 0 else 0.0

    funnel_text = f"""
[bold cyan]1. Vagas Analisadas:[/] {total}
[bold blue]2. Candidaturas Enviadas:[/] {applied}  [dim](100% do funil ativo)[/dim]
[bold green]3. Convites para Entrevista:[/] {interviews}  [bold green]({rate:.1f}% de conversão)[/bold green]
[bold magenta]4. Propostas Recebidas:[/] {offers}
[dim]5. Respostas Negativas / Encerradas:[/] {rejected}
"""
    console.print(Panel(funnel_text, title="🎯 Funil de Conversão de Carreiras", border_style="green"))


@app.command(name="tailor-resume")
def tailor_resume_cmd(
    target: str = typer.Argument(..., help="URL ou ID da vaga no banco para gerar o currículo sob medida"),
):
    """Gera um currículo em PDF sob medida (ATS-friendly) adaptado para as exigências da vaga."""
    profile = load_candidate_profile()
    llm = LLMEngine()

    if target.isdigit():
        jobs = list_jobs()
        job = next((j for j in jobs if j.id == int(target)), None)
        if not job:
            console.print(f"[bold red]Vaga com ID #{target} não encontrada no banco.[/]")
            return
        console.print(Panel.fit(f"[bold cyan]Gerando Currículo ATS Sob Medida para:[/] #{job.id} - {job.title} @ {job.company}", border_style="blue"))
    else:
        console.print(Panel.fit(f"[bold cyan]Gerando Currículo ATS Sob Medida para:[/] {target}", border_style="blue"))
        with console.status("[bold green]Coletando dados da vaga..."):
            job = fetch_job_details(target)

    if not job:
        console.print("[bold red]Não foi possível extrair informações desta página.[/]")
        return

    with console.status("[bold green]Compilando currículo sob medida em PDF..."):
        tailor = ResumeTailor(profile=profile, llm_engine=llm)
        pdf_path = tailor.generate_tailored_pdf(job)

    console.print(f"[bold green]✓ Currículo gerado com sucesso![/]")
    console.print(f"Arquivo: [bold cyan]{pdf_path}[/]")
    console.print("[dim]Dica: Este PDF prioriza as palavras-chave e requisitos exigidos pelo ATS da vaga.[/dim]")


@app.command(name="cover-letter")
def cover_letter_cmd(
    target: str = typer.Argument(..., help="URL ou ID da vaga no banco para gerar a carta de apresentação"),
):
    """Gera uma Carta de Apresentação (Cover Letter) sob medida com IA para a vaga."""
    profile = load_candidate_profile()
    llm = LLMEngine()

    if target.isdigit():
        jobs = list_jobs()
        job = next((j for j in jobs if j.id == int(target)), None)
        if not job:
            console.print(f"[bold red]Vaga com ID #{target} não encontrada no banco.[/]")
            return
        console.print(Panel.fit(f"[bold cyan]Gerando Carta de Apresentação para:[/] #{job.id} - {job.title} @ {job.company}", border_style="magenta"))
    else:
        console.print(Panel.fit(f"[bold cyan]Gerando Carta de Apresentação para:[/] {target}", border_style="magenta"))
        with console.status("[bold green]Coletando dados da vaga..."):
            job = fetch_job_details(target)
        job = fetch_job_details(url)

    if not job:
        console.print("[bold red]Não foi possível extrair informações desta página.[/]")
        return

    with console.status("[bold green]Redigindo carta personalizada com IA..."):
        letter = llm.generate_cover_letter(job, profile)
        job.cover_letter = letter
        job = save_job(job)

    console.print(Panel(letter, title=f"[bold]Carta de Apresentação - {job.title} @ {job.company}[/]", border_style="green"))
    console.print("[dim]✓ Carta salva no banco de dados e pronta para uso![/dim]")


@app.command()
def export(
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Caminho do arquivo CSV de destino")
):
    """Exporta o histórico de vagas e candidaturas para uma planilha CSV."""
    p = Path(output) if output else None
    saved_path = export_to_csv(p)
    console.print(f"[bold green]✓ Histórico exportado com sucesso para:[/] [bold]{saved_path}[/]")


@app.command()
def test_local(
    headless: bool = typer.Option(False, "--headless", help="Roda em segundo plano sem janela visível"),
):
    """Executa um teste local imediato em um formulário simulado para verificar o agente."""
    form_file = BASE_DIR / "data" / "test_form.html"
    if not form_file.exists():
        console.print("[red]Arquivo test_form.html não encontrado.[/]")
        return

    test_url = f"file:///{form_file.resolve().as_posix()}"
    console.print(Panel.fit("[bold green]🧪 Teste Local de Automação de Candidatura[/]", border_style="green"))
    console.print(f"Abrindo formulário de teste: [dim]{test_url}[/dim]")

    profile = load_candidate_profile()
    test_job = Job(
        title="Desenvolvedor Backend Pleno (Python / Node.js)",
        company="TechCorp Soluções Digitais",
        url=test_url,
        platform="local-test",
        location="São Paulo, SP",
        workplace_type="Remoto",
        description="Buscamos pessoa desenvolvedora com experiência em desenvolvimento de microsserviços.",
        fit_score=95,
        fit_summary="Vaga perfeita para o perfil técnico em Python e FastAPI.",
    )
    test_job = save_job(test_job)

    applicant = JobApplicant(profile=profile, headless=headless)
    applicant.run_application(test_job, auto_submit=False)


@app.command()
def history(
    status: Optional[str] = typer.Option(None, "--status", help="Filtrar por status: applied, pending, skipped, failed")
):
    """Exibe o histórico e estatísticas de todas as vagas processadas."""
    stats = get_stats()
    stats_text = f"[bold]Total:[/] {stats['total']}  |  [green bold]Aplicadas:[/] {stats['applied']}  |  [yellow]Pendentes:[/] {stats['pending']}  |  [dim]Ignoradas:[/] {stats['skipped']}"
    console.print(Panel(stats_text, title="📊 Resumo Geral", border_style="cyan"))

    jobs = list_jobs(status=status)
    if not jobs:
        console.print("[dim]Nenhuma candidatura registrada ainda.[/dim]")
        return

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("ID", justify="center", width=4)
    table.add_column("Cargo", min_width=25)
    table.add_column("Empresa", min_width=15)
    table.add_column("Fit", justify="center", width=8)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Data", justify="center", width=12)

    for j in jobs:
        st_color = "green" if j.status == "applied" else ("yellow" if j.status == "pending" else "dim")
        fit_str = f"{j.fit_score}%" if j.fit_score is not None else "-"
        date_str = (j.applied_at or j.created_at or "")[:10]
        table.add_row(f"#{j.id}", j.title, j.company, fit_str, f"[{st_color}]{j.status}[/{st_color}]", date_str)

    console.print(table)


@app.command()
def outreach(
    job_id: int = typer.Argument(..., help="ID da vaga cadastrada no banco de dados"),
):
    """Gera 5 mensagens estratégicas de networking (LinkedIn <300c, InMail, Cold Email, Follow-up, Thank You)."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        console.print(f"[bold red]Vaga com ID #{job_id} não encontrada no banco.[/]")
        return

    profile = load_candidate_profile()
    coach = NetworkingCoach(profile)

    with console.status(f"[bold green]Gerando mensagens de networking para {job.company}..."):
        messages = coach.generate_all_messages(job)

    lang_tag = "[cyan](Inglês)[/]" if messages.get("is_english") else "[green](Português)[/]"
    console.print(Panel.fit(f"[bold green]💬 Mensagens Estratégicas de Networking & Cold Outreach[/] {lang_tag}\nVaga: [bold]{job.title}[/] @ [bold]{job.company}[/]", border_style="cyan"))

    # 1. LinkedIn Conexão
    note = messages["linkedin_connection_note"]
    console.print(Panel(
        f"{note}\n\n[dim]Contagem: {len(note)}/300 caracteres (Limite do LinkedIn)[/dim]",
        title="[bold blue]1. Nota de Convite no LinkedIn (< 300 caracteres)[/]",
        border_style="blue"
    ))

    # 2. LinkedIn InMail
    inmail = messages["linkedin_inmail"]
    console.print(Panel(
        inmail,
        title="[bold cyan]2. InMail / Mensagem Direta do LinkedIn[/]",
        border_style="cyan"
    ))

    # 3. Cold Email Tech Lead
    cold = messages["cold_email_hiring_manager"]
    console.print(Panel(
        cold,
        title="[bold magenta]3. Cold Email para Hiring Manager / Tech Lead[/]",
        border_style="magenta"
    ))

    # 4. Follow-up 7 dias
    follow = messages["follow_up_7days"]
    console.print(Panel(
        follow,
        title="[bold yellow]4. Follow-up Educado (7 dias sem resposta)[/]",
        border_style="yellow"
    ))

    # 5. Thank You pós-entrevista
    thank = messages["thank_you_interview"]
    console.print(Panel(
        thank,
        title="[bold green]5. Agradecimento Pós-Entrevista (Thank You Note)[/]",
        border_style="green"
    ))


@app.command()
def roadmap(
    job_id: int = typer.Argument(..., help="ID da vaga cadastrada no banco de dados"),
):
    """Gera um plano de aceleração técnica e sprint de 7 dias para as lacunas da vaga."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        console.print(f"[bold red]Vaga com ID #{job_id} não encontrada no banco.[/]")
        return

    profile = load_candidate_profile()
    roadmap_gen = SkillGapRoadmap(profile)

    with console.status(f"[bold purple]Elaborando plano de aceleração para as lacunas de {job.title}..."):
        roadmap_md = roadmap_gen.generate_roadmap(job)

    import re
    clean_company = re.sub(r"[^a-zA-Z0-9_-]", "_", job.company.lower())
    saved_file = BASE_DIR / "data" / f"roadmap_estudos_{clean_company}_{job.id}.md"
    saved_file.write_text(roadmap_md, encoding="utf-8")

    from rich.markdown import Markdown
    console.print(Panel(Markdown(roadmap_md), title=f"[bold purple]🚀 Sprint de 7 Dias: {job.title} @ {job.company}[/]", border_style="purple"))
    console.print(f"[bold green]✓ Roteiro de estudos salvo em:[/] [bold]{saved_file}[/]")


@app.command()
def kanban():
    """Exibe o quadro Kanban completo das candidaturas direto no terminal."""
    jobs = list_jobs()
    if not jobs:
        console.print("[dim]Nenhuma vaga cadastrada no banco.[/dim]")
        return

    columns = {
        "pending": ("[bold yellow]PENDENTES[/]", [j for j in jobs if j.status == "pending"]),
        "applied": ("[bold blue]APLICADAS[/]", [j for j in jobs if j.status == "applied"]),
        "interview": ("[bold green]ENTREVISTAS 🎉[/]", [j for j in jobs if j.status == "interview"]),
        "offer": ("[bold magenta]OFERTAS 🚀[/]", [j for j in jobs if j.status == "offer"]),
        "rejected": ("[bold red]REJEITADAS[/]", [j for j in jobs if j.status == "rejected"]),
    }

    table = Table(title="📋 Quadro Kanban de Candidaturas", show_header=True, header_style="bold white")
    for key, (header, items) in columns.items():
        table.add_column(f"{header} ({len(items)})", min_width=22)

    max_rows = max(len(items) for _, items in columns.values()) if any(columns.values()) else 0

    for i in range(max_rows):
        row_cells = []
        for key, (_, items) in columns.items():
            if i < len(items):
                j = items[i]
                fit_text = f"Fit: {j.fit_score}%" if j.fit_score else ""
                row_cells.append(f"[bold]#{j.id}[/] {j.title[:18]}...\n[dim]{j.company[:18]}[/] {fit_text}")
            else:
                row_cells.append("")
        table.add_row(*row_cells)

    console.print(table)


@app.command()
def login(
    platform: str = typer.Argument(..., help="Plataforma para login: linkedin, gupy, indeed, catho, infojobs, greenhouse"),
):
    """Faz login interativo em uma plataforma de vagas e salva a sessão para reutilizar."""
    console.print(Panel.fit(f"[bold cyan]🔐 Login na Plataforma:[/] {platform}", border_style="green"))

    if platform not in PLATFORMS:
        console.print(f"[red]Plataforma '{platform}' não reconhecida.[/]")
        console.print(f"[cyan]Plataformas disponíveis:[/] {', '.join(PLATFORMS.keys())}")
        return

    session_mgr = SessionManager()

    # Verifica se já tem sessão
    if session_mgr.has_session(platform):
        info = session_mgr.get_session_info(platform)
        user = info.get("user_info", "desconhecido") if info else "desconhecido"
        console.print(f"[green]✓ Já existe sessão ativa do {PLATFORMS[platform]['name']}[/]")
        console.print(f"[dim]  Logado como: {user}[/]")
        renew = console.input("[yellow]Deseja renovar o login? (s/n): [/]").strip().lower()
        if renew not in ["s", "sim", "y"]:
            return

    success = session_mgr.interactive_login(platform)
    if success:
        console.print(f"[bold green]✅ Login salvo com sucesso! A sessão será reutilizada nas próximas candidaturas.[/]")
    else:
        console.print(f"[red]Login não completado. Tente novamente.[/]")


@app.command()
def sessions():
    """Lista todas as sessões de login ativas e seus status."""
    console.print(Panel.fit("[bold cyan]📋 Sessões de Login Salvas[/]", border_style="cyan"))

    session_mgr = SessionManager()
    all_sessions = session_mgr.list_sessions()

    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Plataforma", min_width=12)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Usuário", min_width=20)
    table.add_column("Login em", width=20)

    for s in all_sessions:
        if s["has_session"]:
            status = "[bold green]✅ Ativa[/]"
            user = s["user_info"] or "-"
            date = (s["saved_at"] or "")[:19].replace("T", " ")
        else:
            status = "[dim]⬚ Sem login[/]"
            user = "-"
            date = "-"
        table.add_row(s["name"], status, user, date)

    console.print(table)
    console.print("\n[dim]Para fazer login: python main.py login <plataforma>[/]")
    console.print("[dim]Plataformas: linkedin, gupy, indeed, catho, infojobs, greenhouse[/]")


@app.command()
def logout(
    platform: str = typer.Argument(..., help="Plataforma para remover sessão"),
):
    """Remove a sessão salva de uma plataforma (logout)."""
    session_mgr = SessionManager()
    session_mgr.remove_session(platform)


@app.command(name="smart-apply")
def smart_apply_cmd(
    url: str = typer.Argument(..., help="URL da vaga (LinkedIn, Gupy ou qualquer plataforma)"),
    auto_submit: bool = typer.Option(False, "--auto-submit", help="Submete sem confirmação humana"),
    headless: bool = typer.Option(False, "--headless", help="Roda o navegador sem interface visível"),
    tailor: bool = typer.Option(True, "--tailor/--no-tailor", help="Gera currículo sob medida"),
):
    """Candidatura inteligente: detecta a plataforma, usa sessão logada se disponível, e aplica da melhor forma.

    Se você estiver logado no LinkedIn/Gupy → usa Easy Apply.
    Se não → usa o fluxo padrão de preenchimento de formulário.
    """
    console.print(Panel.fit(f"[bold cyan]🎯 Smart Apply:[/] {url}", border_style="blue"))

    profile = load_candidate_profile()
    llm = LLMEngine()
    session_mgr = SessionManager()

    # 1. Detecta a plataforma
    platform = session_mgr.detect_platform(url)
    if platform:
        console.print(f"[cyan]📌 Plataforma detectada:[/] [bold]{PLATFORMS[platform]['name']}[/]")
    else:
        console.print("[dim]Plataforma não reconhecida — usando candidatura genérica.[/]")

    # 2. Analisa a vaga
    with console.status("[bold green]Coletando dados da vaga..."):
        job = fetch_job_details(url)

    if not job:
        console.print("[bold red]Não foi possível extrair informações desta vaga.[/]")
        return

    with console.status("[bold green]Analisando fit com seu perfil..."):
        score, summary, matched, missing = llm.evaluate_fit(job, profile)
        job.fit_score = score
        job.fit_summary = summary
        job.skills_matched = matched
        job.skills_missing = missing
        job = save_job(job)

    color = "green" if score >= 75 else ("yellow" if score >= 60 else "red")
    console.print(f"[bold]Fit Score:[/] [{color} bold]{score}/100[/{color} bold]  |  {job.title} @ {job.company}")

    # 3. Escolhe a melhor estratégia de candidatura
    if platform == "linkedin" and session_mgr.has_session("linkedin"):
        console.print("[bold green]🔗 Usando LinkedIn Easy Apply (sessão autenticada)![/]")
        linkedin_app = LinkedInApplier(profile=profile, headless=headless)
        linkedin_app.apply(job, auto_submit=auto_submit)
    elif platform and session_mgr.has_session(platform):
        console.print(f"[bold green]🔗 Sessão {PLATFORMS[platform]['name']} detectada → candidatura autenticada![/]")
        # Para outras plataformas, usa o applicant padrão com contexto autenticado
        applicant = JobApplicant(profile=profile, headless=headless, tailor_resume=tailor)
        applicant.run_application(job, auto_submit=auto_submit)
    else:
        if platform:
            console.print(f"[yellow]⚠ Sem sessão do {PLATFORMS[platform]['name']}. Usando candidatura como visitante.[/]")
            console.print(f"[dim]Dica: python main.py login {platform}[/]")
        applicant = JobApplicant(profile=profile, headless=headless, tailor_resume=tailor)
        applicant.run_application(job, auto_submit=auto_submit)


@app.command(name="ats-check")
def ats_check_cmd(
    target: str = typer.Argument(..., help="ID da vaga no banco (ex: 1) ou URL da vaga"),
    cv_path: Optional[str] = typer.Option(None, "--cv", help="Caminho alternativo para o PDF do currículo"),
):
    """Audita a compatibilidade do seu currículo contra os robôs ATS (Applicant Tracking Systems)."""
    profile = load_candidate_profile()
    llm = LLMEngine()
    scanner = ATSCompatibilityScanner(profile, llm)

    job: Optional[Job] = None
    if target.isdigit():
        jobs = list_jobs()
        job = next((j for j in jobs if j.id == int(target)), None)
    else:
        with console.status("[bold green]Coletando dados da vaga..."):
            job = fetch_job_details(target)

    if not job:
        console.print("[bold red]Vaga não encontrada no banco nem na URL informada.[/]")
        return

    console.print(Panel.fit(f"[bold cyan]🔍 Auditoria ATS:[/] {job.title} @ {job.company}", border_style="cyan"))

    with console.status("[bold green]Escaneando densidade de palavras-chave, formatação e métricas..."):
        audit = scanner.scan(job, custom_resume_path=cv_path)

    score = audit["overall_score"]
    color = "green" if score >= 80 else ("yellow" if score >= 60 else "red")

    summary_text = f"""
[bold]Score Geral de Aprovação ATS:[/] [{color} bold]{score}%[/{color} bold]

[bold cyan]1. Hard Skills Pedidas:[/] {', '.join(audit['skills_analysis']['demanded_skills']) or 'N/A'}
[bold green]✓ Skills Encontradas no CV:[/] {', '.join(audit['skills_analysis']['matched_skills']) or 'Nenhuma'}
[bold red]✗ Palavras-chave Faltantes:[/] {', '.join(audit['skills_analysis']['missing_skills']) or 'Nenhuma lacuna crítica'}

[bold cyan]2. Formatação & Parseabilidade:[/] {audit['formatting_analysis']['score']}/100 pts ({audit['formatting_analysis']['word_count']} palavras legíveis)
[bold cyan]3. Métricas Quantificadas:[/] {audit['impact_analysis']['quantified_metrics_found']} indicadores numéricos encontrados no texto
"""
    console.print(Panel(summary_text, title="📊 Diagnóstico do Filtro ATS", border_style=color))

    rec_table = Table(title="💡 Recomendações Acionáveis para Aumentar o Score", show_header=True, header_style="bold yellow")
    rec_table.add_column("#", justify="center", width=4)
    rec_table.add_column("Recomendação", min_width=50)

    for i, tip in enumerate(audit["recommendations"], 1):
        rec_table.add_row(str(i), tip)

    console.print(rec_table)


@app.command(name="salary-advisor")
def salary_advisor_cmd(
    target: str = typer.Argument(..., help="ID da vaga no banco (ex: 1) ou URL da vaga"),
):
    """Gera estimativa de faixa salarial justa e script de negociação com RH."""
    profile = load_candidate_profile()
    advisor = SalaryAdvisor(profile)

    job: Optional[Job] = None
    if target.isdigit():
        jobs = list_jobs()
        job = next((j for j in jobs if j.id == int(target)), None)
    else:
        with console.status("[bold green]Coletando dados da vaga..."):
            job = fetch_job_details(target)

    if not job:
        console.print("[bold red]Vaga não encontrada.[/]")
        return

    console.print(Panel.fit(f"[bold green]💰 Consultor Salarial:[/] {job.title} @ {job.company}", border_style="green"))
    advice = advisor.advise(job)

    salary_text = f"""
[bold]Categoria Mapeada:[/] {advice['role_category']}
[bold green]Faixa Salarial Sugerida (CLT):[/] [bold]{advice['recommended_clt_range']}[/] (Alvo: {advice['recommended_clt_target']})
[bold cyan]Equivalente Estimado (PJ):[/] [bold]{advice['recommended_pj_target']}[/]

[bold yellow]Resposta Pronta para Formulários Online:[/]
[dim]"{advice['form_answer']}"[/dim]

[bold yellow]Script de Resposta para a Triagem Telefônica com RH:[/]
"{advice['interview_pitch']}"
"""
    console.print(Panel(salary_text, title="💵 Estimativa de Mercado & Ancoragem", border_style="green"))

    prop_table = Table(title="🎯 Argumentos de Valor para Justificar sua Pretensão", show_header=True, header_style="bold cyan")
    prop_table.add_column("Pontos Fortes Baseados no seu Histórico Real", min_width=50)
    for p in advice["value_propositions"]:
        prop_table.add_row(f"• {p}")
    console.print(prop_table)


@app.command(name="safety")
def safety_cmd():
    """Exibe o status do Guarda de Segurança Anti-Ban e limites diários de candidatura."""
    guard = SafetyGuard()
    status = guard.get_status_report()

    console.print(Panel.fit("[bold cyan]🛡️ Status do Guarda de Segurança Anti-Ban[/]", border_style="cyan"))

    hours_status = "[green]✓ Horário comercial ativo (comportamento humano seguro)[/]" if status["is_work_hours"] else "[yellow]! Fora de horário comercial (08h às 20h) - use com cautela[/]"

    info_text = f"""
[bold]Data:[/] {status['date']}
[bold]Candidaturas Hoje:[/] [bold green]{status['total_today']}[/] de [bold]{status['limit_total']}[/] permitidas
[bold]Margem Restante:[/] [bold cyan]{status['remaining_total']}[/] candidaturas seguras hoje
[bold]Limite por Plataforma:[/] {status['limit_per_platform']} por dia (ex: max {status['limit_per_platform']} no LinkedIn)
[bold]Janela de Atividade:[/] {hours_status}
"""
    console.print(Panel(info_text, title="Métricas de Proteção", border_style="green"))

    if status["by_platform"]:
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Plataforma", min_width=15)
        table.add_column("Envios Hoje", justify="center", width=12)
        for plat, count in status["by_platform"].items():
            table.add_row(plat.title(), str(count))
        console.print(table)


if __name__ == "__main__":
    app()
