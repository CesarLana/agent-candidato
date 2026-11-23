"""Painel de Controle Visual Web (FastAPI + Tailwind CSS).

Oferece uma interface gráfica intuitiva para acompanhar o funil de vagas,
Kanban interativo drag-and-drop, editor de perfil, geração de mensagens de networking,
roadmap de estudo para lacunas técnicas, download de currículos sob medida e candidaturas diretas.
"""

from pathlib import Path
from typing import List, Optional
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from automation.applicant import JobApplicant
from automation.safety_guard import SafetyGuard
from automation.session_manager import SessionManager, PLATFORMS
from automation.linkedin_applier import LinkedInApplier
from core.ats_scanner import ATSCompatibilityScanner
from core.config import load_candidate_profile, save_candidate_profile
from core.database import export_to_csv, get_job_by_url, get_stats, list_jobs, save_job, update_job_status
from core.interview_coach import InterviewCoach
from core.llm import LLMEngine
from core.models import CandidateProfile, Job
from core.networking import NetworkingCoach
from core.resume_tailor import ResumeTailor
from core.salary_advisor import SalaryAdvisor
from core.skill_roadmap import SkillGapRoadmap
from scheduler.hunter import JobHunterDaemon
from scrapers import fetch_job_details
from scrapers.gupy import search_gupy_jobs
from scrapers.linkedin_search import search_linkedin_jobs

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(
    title="Agente Candidato - Dashboard Pro",
    description="Centro de Inteligência de Carreiras, Candidaturas e Networking",
    version="5.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeJobRequest(BaseModel):
    url: str


class SearchJobsRequest(BaseModel):
    keyword: str
    location: str = "São Paulo"
    platforms: List[str] = ["linkedin", "gupy"]
    max_results: int = 15


class UpdateStatusRequest(BaseModel):
    status: str
    notes: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def index_page():
    """Renderiza o Painel Visual completo em HTML com Tailwind CSS."""
    html_file = Path(__file__).resolve().parent / "index.html"
    if html_file.exists():
        with open(html_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Dashboard HTML não encontrado.</h1>"


@app.get("/api/jobs")
def api_list_jobs(status: Optional[str] = None):
    """Lista todas as vagas cadastradas com fit score e status."""
    jobs = list_jobs(status=status)
    return [j.dict() for j in jobs]


@app.get("/api/stats")
def api_get_stats():
    """Retorna estatísticas gerais e métricas do funil."""
    jobs = list_jobs()
    total = len(jobs)
    applied = sum(1 for j in jobs if j.status == "applied")
    interviews = sum(1 for j in jobs if j.status == "interview")
    offers = sum(1 for j in jobs if j.status == "offer")
    rejected = sum(1 for j in jobs if j.status == "rejected")
    pending = sum(1 for j in jobs if j.status == "pending")

    avg_fit = int(sum(j.fit_score or 0 for j in jobs) / total) if total > 0 else 0
    conv_rate = round((interviews / applied * 100), 1) if applied > 0 else 0.0

    return {
        "total": total,
        "applied": applied,
        "interviews": interviews,
        "offers": offers,
        "rejected": rejected,
        "pending": pending,
        "avg_fit": avg_fit,
        "conversion_rate": conv_rate,
    }


@app.post("/api/jobs/search-live")
def api_search_live(req: SearchJobsRequest):
    """Busca vagas em tempo real no LinkedIn e Gupy com IA e salva no banco SQLite."""
    keyword = req.keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="Digite uma palavra-chave para buscar.")

    profile = load_candidate_profile()
    llm = LLMEngine()
    discovered_jobs: List[Job] = []

    # 1. Busca no LinkedIn se selecionado
    if "linkedin" in req.platforms:
        try:
            li_local = search_linkedin_jobs(
                keywords=keyword,
                location=req.location,
                remote_only=False,
                max_results=req.max_results,
            )
            discovered_jobs.extend(li_local)
        except Exception:
            pass

        # Se São Paulo ou Remoto, busca também vagas remotas Brasil
        loc_lower = req.location.lower()
        if "são paulo" in loc_lower or "sp" in loc_lower or "remoto" in loc_lower or "brasil" in loc_lower:
            try:
                li_rem = search_linkedin_jobs(
                    keywords=keyword,
                    location="Brazil",
                    remote_only=True,
                    max_results=max(5, req.max_results // 2),
                )
                discovered_jobs.extend(li_rem)
            except Exception:
                pass

    # 2. Busca na Gupy se selecionada
    if "gupy" in req.platforms:
        try:
            gupy_jobs = search_gupy_jobs(term=keyword, max_results=req.max_results)
            discovered_jobs.extend(gupy_jobs)
        except Exception:
            pass

    new_saved_jobs = []
    skipped_count = 0

    for raw_job in discovered_jobs:
        existing = get_job_by_url(raw_job.url)
        if existing:
            skipped_count += 1
            continue

        full_job = fetch_job_details(raw_job.url) or raw_job
        score, summary, matched, missing = llm.evaluate_fit(full_job, profile)
        full_job.fit_score = score
        full_job.fit_summary = summary
        full_job.skills_matched = matched
        full_job.skills_missing = missing

        # Salva a vaga
        saved = save_job(full_job)
        new_saved_jobs.append(saved.dict())

    return {
        "success": True,
        "keyword": keyword,
        "total_discovered": len(discovered_jobs),
        "new_saved": len(new_saved_jobs),
        "already_existing": skipped_count,
        "jobs": new_saved_jobs,
    }


@app.post("/api/jobs/analyze")
def api_analyze_job(req: AnalyzeJobRequest):
    """Analisa uma vaga pela URL ou executa busca se for palavra-chave / link de pesquisa."""
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Digite uma URL ou termo de busca.")

    # Se não for URL (ex: digitou apenas "DevOps" ou "Infraestrutura")
    if not url.startswith("http://") and not url.startswith("https://"):
        return api_search_live(SearchJobsRequest(keyword=url))

    # Se for uma URL de pesquisa de vagas do LinkedIn ou Gupy
    if "linkedin.com/jobs/search" in url or "portal.gupy.io/job-search" in url:
        import urllib.parse
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        kw = params.get("keywords", [""])[0] or params.get("term", [""])[0]
        if not kw and "term=" in url:
            kw = url.split("term=")[-1].split("&")[0]
        if kw:
            return api_search_live(SearchJobsRequest(keyword=urllib.parse.unquote(kw)))

    profile = load_candidate_profile()
    llm = LLMEngine()

    job = fetch_job_details(url)
    if not job:
        raise HTTPException(status_code=404, detail="Não foi possível extrair dados da página.")

    score, summary, matched, missing = llm.evaluate_fit(job, profile)
    job.fit_score = score
    job.fit_summary = summary
    job.skills_matched = matched
    job.skills_missing = missing

    # Gera carta de apresentação automaticamente
    job.cover_letter = llm.generate_cover_letter(job, profile)
    saved_job = save_job(job)

    # Gera currículo sob medida em background
    try:
        tailor = ResumeTailor(profile, llm)
        tailor.generate_tailored_pdf(saved_job)
    except Exception:
        pass

    return saved_job.dict()


@app.post("/api/jobs/{job_id}/status")
def api_update_status(job_id: int, req: UpdateStatusRequest):
    """Atualiza o status de uma vaga (ex: mover para interview, applied, offer)."""
    update_job_status(job_id=job_id, status=req.status, notes=req.notes)
    return {"success": True, "job_id": job_id, "new_status": req.status}


@app.get("/api/jobs/{job_id}/resume")
def api_download_resume(job_id: int):
    """Gera e retorna o PDF do currículo ATS sob medida para download."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    tailor = ResumeTailor(profile)
    pdf_path = tailor.generate_tailored_pdf(job)

    if not pdf_path.exists():
        raise HTTPException(status_code=500, detail="Erro ao compilar PDF.")

    return FileResponse(
        path=str(pdf_path),
        filename=pdf_path.name,
        media_type="application/pdf",
    )


@app.get("/api/jobs/{job_id}/interview-prep")
def api_get_interview_prep(job_id: int):
    """Gera e retorna o roteiro de preparação para entrevista da vaga."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    coach = InterviewCoach(profile)
    prep_md = coach.generate_prep_guide(job)

    return {"job_id": job_id, "company": job.company, "title": job.title, "guide_markdown": prep_md}


@app.get("/api/jobs/{job_id}/outreach")
def api_get_outreach(job_id: int):
    """Gera as 5 mensagens de networking e cold outreach personalizadas."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    networking = NetworkingCoach(profile)
    messages = networking.generate_all_messages(job)

    return {
        "job_id": job_id,
        "company": job.company,
        "title": job.title,
        **messages,
    }


@app.get("/api/jobs/{job_id}/roadmap")
def api_get_skill_roadmap(job_id: int):
    """Gera o roteiro de estudos de 7 dias para as habilidades faltantes."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    roadmap_gen = SkillGapRoadmap(profile)
    roadmap_md = roadmap_gen.generate_roadmap(job)

    return {
        "job_id": job_id,
        "company": job.company,
        "title": job.title,
        "roadmap_markdown": roadmap_md,
    }


@app.get("/api/jobs/{job_id}/ats-check")
def api_get_ats_check(job_id: int):
    """Audita a compatibilidade ATS do currículo para esta vaga."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    scanner = ATSCompatibilityScanner(profile)
    audit = scanner.scan(job)
    return audit


@app.get("/api/jobs/{job_id}/salary-advisor")
def api_get_salary_advisor(job_id: int):
    """Gera estimativa e pitch de negociação salarial para a vaga."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    profile = load_candidate_profile()
    advisor = SalaryAdvisor(profile)
    return advisor.advise(job)


@app.get("/api/safety-status")
def api_get_safety_status():
    """Retorna o status do guarda de segurança anti-ban e limites diários."""
    guard = SafetyGuard()
    return guard.get_status_report()


@app.post("/api/jobs/{job_id}/apply")
def api_apply_job(job_id: int, background_tasks: BackgroundTasks):
    """Dispara a candidatura automática via navegador em segundo plano."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    def run_applicant_task():
        try:
            profile = load_candidate_profile()
            applicant = JobApplicant(profile=profile, headless=True)
            applicant.apply_to_job(job, auto_submit=True, headless=True)
        except Exception as e:
            print(f"[Dashboard] Erro ao aplicar para vaga {job.id}: {e}")

    background_tasks.add_task(run_applicant_task)
    return {"message": f"Candidatura automática iniciada para '{job.title}' @ {job.company}!"}


@app.get("/api/profile")
def api_get_profile():
    """Retorna os dados completos do perfil do candidato."""
    profile = load_candidate_profile()
    return profile.dict()


@app.post("/api/profile")
def api_save_profile(updated_profile: CandidateProfile):
    """Atualiza e persiste o perfil do candidato no profile.yaml."""
    saved_path = save_candidate_profile(updated_profile)
    return {"success": True, "message": f"Perfil salvo com sucesso em {saved_path.name}!"}


@app.post("/api/hunt")
def api_trigger_hunt(background_tasks: BackgroundTasks):
    """Dispara um ciclo de caça de vagas em segundo plano."""
    def run_hunt():
        daemon = JobHunterDaemon()
        daemon.run_hunt_cycle(auto_apply=False, headless=True)

    background_tasks.add_task(run_hunt)
    return {"message": "Ciclo do Caçador iniciado em segundo plano!"}


@app.get("/api/export-csv")
def api_export_csv():
    """Gera e baixa a planilha CSV completa das vagas."""
    csv_path = export_to_csv()
    return FileResponse(
        path=str(csv_path),
        filename="candidaturas.csv",
        media_type="text/csv",
    )


# ═══════════════════════════════════════════════════════════════
#  SESSÕES & LOGIN
# ═══════════════════════════════════════════════════════════════

@app.get("/api/sessions")
def api_list_sessions():
    """Lista todas as sessões de login ativas e seus status."""
    session_mgr = SessionManager()
    return session_mgr.list_sessions()


class LoginCredentialsRequest(BaseModel):
    email: str
    password: str


class CookieSessionRequest(BaseModel):
    cookie_value: str


@app.post("/api/sessions/{platform}/auth")
def api_login_auth(platform: str, req: LoginCredentialsRequest):
    """Autentica com e-mail e senha diretamente pelo servidor."""
    session_mgr = SessionManager()
    res = session_mgr.login_with_credentials(platform, req.email, req.password)
    return res


@app.post("/api/sessions/{platform}/cookie")
def api_save_cookie(platform: str, req: CookieSessionRequest):
    """Salva a sessão diretamente a partir do cookie principal (ex: li_at)."""
    session_mgr = SessionManager()
    res = session_mgr.save_cookie_session(platform, req.cookie_value)
    return res


@app.post("/api/sessions/{platform}/login")
def api_start_login(platform: str, background_tasks: BackgroundTasks):
    """Inicia login interativo para uma plataforma (abre navegador)."""
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Plataforma '{platform}' não suportada. Use: {', '.join(PLATFORMS.keys())}")

    def run_login():
        session_mgr = SessionManager()
        session_mgr.interactive_login(platform)

    background_tasks.add_task(run_login)
    return {"message": f"Navegador aberto para login no {PLATFORMS[platform]['name']}. Faça login na janela que apareceu."}


@app.delete("/api/sessions/{platform}")
def api_logout(platform: str):
    """Remove a sessão salva de uma plataforma."""
    session_mgr = SessionManager()
    removed = session_mgr.remove_session(platform)
    return {"success": removed, "platform": platform}


class SmartApplyRequest(BaseModel):
    headless: Optional[bool] = False
    auto_submit: Optional[bool] = False


@app.post("/api/jobs/{job_id}/smart-apply")
def api_smart_apply(job_id: int, background_tasks: BackgroundTasks, req: Optional[SmartApplyRequest] = None):
    """Candidatura inteligente: detecta plataforma, usa sessão se disponível."""
    jobs = list_jobs()
    job = next((j for j in jobs if j.id == job_id), None)
    if not job:
        raise HTTPException(status_code=404, detail="Vaga não encontrada.")

    headless = req.headless if req else False
    auto_submit = req.auto_submit if req else False

    session_mgr = SessionManager()
    platform = session_mgr.detect_platform(job.url)
    strategy = "guest"

    if platform == "linkedin" and session_mgr.has_session("linkedin"):
        strategy = "linkedin_easy_apply"
    elif platform and session_mgr.has_session(platform):
        strategy = f"{platform}_authenticated"

    def run_smart_apply():
        try:
            profile = load_candidate_profile()
            if strategy == "linkedin_easy_apply":
                applier = LinkedInApplier(profile=profile, headless=headless)
                applier.apply(job, auto_submit=auto_submit)
            else:
                applicant = JobApplicant(profile=profile, headless=headless)
                applicant.apply_to_job(job, auto_submit=auto_submit, headless=headless)
        except Exception as e:
            print(f"[Dashboard] Erro ao aplicar para vaga {job.id}: {e}")

    background_tasks.add_task(run_smart_apply)
    mode_text = "em segundo plano" if headless else "em janela visível na sua tela"
    return {
        "message": f"Candidatura iniciada para '{job.title}' @ {job.company} ({mode_text})!",
        "strategy": strategy,
        "platform": platform,
        "headless": headless,
    }
