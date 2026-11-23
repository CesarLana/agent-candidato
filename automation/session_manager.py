"""Gerenciador de sessões persistentes para plataformas de vagas.

Permite que o usuário faça login uma vez (interativamente) e reutilize
a sessão autenticada em todas as candidaturas futuras, evitando:
- Preenchimento duplicado de dados que já estão no perfil logado
- Bloqueios anti-bot (sessão com cookies parece usuário real)
- Impossibilidade de usar "Easy Apply" e candidatura rápida
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from playwright.sync_api import BrowserContext, Page, sync_playwright
from rich.console import Console

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent
SESSIONS_DIR = BASE_DIR / "data" / "sessions"


# ─────────────────────────────────────────────────────────────
#  Plataformas suportadas e suas URLs de login
# ─────────────────────────────────────────────────────────────
PLATFORMS = {
    "linkedin": {
        "name": "LinkedIn",
        "login_url": "https://www.linkedin.com/login",
        "check_url": "https://www.linkedin.com/feed/",
        "logged_in_selector": ".feed-identity-module, .global-nav__me, nav[aria-label='Primary']",
        "logged_out_indicator": "input#username, .login__form",
        "domain": "linkedin.com",
    },
    "gupy": {
        "name": "Gupy",
        "login_url": "https://login.gupy.io/",
        "check_url": "https://login.gupy.io/",
        "logged_in_selector": "[data-testid='user-menu'], .user-avatar, .dashboard",
        "logged_out_indicator": "input[type='email'], .login-form, button:has-text('Entrar')",
        "domain": "gupy.io",
    },
    "greenhouse": {
        "name": "Greenhouse (via Board)",
        "login_url": "https://boards.greenhouse.io/",
        "check_url": "https://boards.greenhouse.io/",
        "logged_in_selector": ".user-menu",
        "logged_out_indicator": "input[type='email']",
        "domain": "greenhouse.io",
    },
    "indeed": {
        "name": "Indeed",
        "login_url": "https://secure.indeed.com/auth",
        "check_url": "https://www.indeed.com/",
        "logged_in_selector": "#userOptionsLabel, [data-gnav-element-name='AccountMenu']",
        "logged_out_indicator": "input#login-email-input",
        "domain": "indeed.com",
    },
    "catho": {
        "name": "Catho",
        "login_url": "https://seguro.catho.com.br/signin/",
        "check_url": "https://www.catho.com.br/area-candidato/",
        "logged_in_selector": ".user-menu, .candidate-area",
        "logged_out_indicator": "input[type='email'], .signin-form",
        "domain": "catho.com.br",
    },
    "infojobs": {
        "name": "InfoJobs",
        "login_url": "https://www.infojobs.com.br/acessar.aspx",
        "check_url": "https://www.infojobs.com.br/",
        "logged_in_selector": ".user-logged, .user-name",
        "logged_out_indicator": "input#email, .login-form",
        "domain": "infojobs.com.br",
    },
}


class SessionManager:
    """Gerencia login e sessões persistentes para plataformas de emprego."""

    def __init__(self, headless: bool = False):
        self.headless = headless
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._playwright = None

    # ─────────────────────────────────────────────────────────
    #  Detecção de plataforma pela URL
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def detect_platform(url: str) -> Optional[str]:
        """Detecta a plataforma de vagas pela URL."""
        url_lower = url.lower()
        for key, info in PLATFORMS.items():
            if info["domain"] in url_lower:
                return key
        return None

    # ─────────────────────────────────────────────────────────
    #  Caminhos de armazenamento
    # ─────────────────────────────────────────────────────────
    @staticmethod
    def _session_file(platform: str) -> Path:
        return SESSIONS_DIR / f"{platform}_session.json"

    @staticmethod
    def _state_dir(platform: str) -> Path:
        return SESSIONS_DIR / f"{platform}_state"

    # ─────────────────────────────────────────────────────────
    #  Verificar sessão existente
    # ─────────────────────────────────────────────────────────
    def has_session(self, platform: str) -> bool:
        """Verifica se existe uma sessão salva para a plataforma."""
        session_file = self._session_file(platform)
        if not session_file.exists():
            return False
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            # Sessão expira após 7 dias por segurança
            saved_at = datetime.fromisoformat(data.get("saved_at", "2000-01-01"))
            age_days = (datetime.now() - saved_at).days
            if age_days > 7:
                console.print(f"[yellow]⚠ Sessão do {PLATFORMS[platform]['name']} expirou ({age_days} dias). Faça login novamente.[/]")
                return False
            return True
        except Exception:
            return False

    def get_session_info(self, platform: str) -> Optional[Dict]:
        """Retorna informações da sessão salva."""
        session_file = self._session_file(platform)
        if session_file.exists():
            try:
                return json.loads(session_file.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def list_sessions(self) -> List[Dict]:
        """Lista todas as sessões salvas com seus status."""
        sessions = []
        for key, info in PLATFORMS.items():
            session_data = self.get_session_info(key)
            sessions.append({
                "platform": key,
                "name": info["name"],
                "has_session": self.has_session(key),
                "saved_at": session_data.get("saved_at") if session_data else None,
                "user_info": session_data.get("user_info", "") if session_data else "",
            })
        return sessions

    # ─────────────────────────────────────────────────────────
    #  Login interativo (abre navegador para o usuário logar)
    # ─────────────────────────────────────────────────────────
    def interactive_login(self, platform: str) -> bool:
        """Abre o navegador na página de login e espera o usuário fazer login manualmente.
        
        Após o login, salva os cookies e estado do navegador para reutilização.
        """
        if platform not in PLATFORMS:
            console.print(f"[red]Plataforma '{platform}' não suportada.[/]")
            console.print(f"Plataformas disponíveis: {', '.join(PLATFORMS.keys())}")
            return False

        info = PLATFORMS[platform]
        console.print(f"\n[bold cyan]🔐 Login no {info['name']}[/]")
        console.print(f"[dim]O navegador será aberto em: {info['login_url']}[/]")
        console.print("[bold yellow]→ Faça login normalmente na janela que abrir.[/]")
        console.print("[dim]O agente detectará automaticamente quando você estiver logado.[/]\n")

        state_dir = self._state_dir(platform)
        state_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()
        
        # Stealth: UserAgent real, viewport real, sem flags de automação
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        try:
            context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(state_dir),
                headless=False,  # Login SEMPRE precisa de tela visível
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
                args=browser_args,
            )

            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(120000)  # 2 min timeout para login

            # Navega para a página de login
            page.goto(info["login_url"], wait_until="domcontentloaded")

            # Aguarda o usuário completar o login (polling a cada 3s)
            console.print("[bold cyan]⏳ Aguardando login...[/] (máximo 5 minutos)")
            max_wait = 300  # 5 minutos
            elapsed = 0
            logged_in = False

            while elapsed < max_wait:
                time.sleep(3)
                elapsed += 3

                # Verifica se está logado
                try:
                    # Checa se existe algum elemento que indica login
                    logged_in_el = page.query_selector(info["logged_in_selector"])
                    if logged_in_el:
                        logged_in = True
                        break

                    # Checa se a URL mudou para uma área autenticada
                    current_url = page.url.lower()
                    if any(w in current_url for w in ["feed", "dashboard", "home", "area-candidato", "mypage"]):
                        # Verifica se o indicador de logout sumiu
                        logout_el = page.query_selector(info["logged_out_indicator"])
                        if not logout_el:
                            logged_in = True
                            break
                except Exception:
                    continue

                # Feedback visual a cada 15s
                if elapsed % 15 == 0:
                    console.print(f"[dim]  ... aguardando ({elapsed}s)...[/dim]")

            if logged_in:
                console.print(f"[bold green]✅ Login no {info['name']} detectado com sucesso![/]")
                
                # Extrai info do usuário se possível
                user_info = self._extract_user_info(page, platform)
                
                # Salva os cookies e storage state
                storage = context.storage_state()
                
                session_data = {
                    "platform": platform,
                    "saved_at": datetime.now().isoformat(),
                    "user_info": user_info,
                    "cookies_count": len(storage.get("cookies", [])),
                    "storage_state": storage,
                }
                
                session_file = self._session_file(platform)
                session_file.write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
                
                console.print(f"[green]💾 Sessão salva em: {session_file.name}[/]")
                console.print(f"[dim]Cookies salvos: {session_data['cookies_count']}[/]")
                if user_info:
                    console.print(f"[cyan]👤 Logado como: {user_info}[/]")
            else:
                console.print(f"[red]❌ Tempo esgotado. Login no {info['name']} não detectado.[/]")
                console.print("[yellow]Dica: Tente novamente ou verifique se o login foi concluído.[/]")

            context.close()
            self._playwright.stop()
            self._playwright = None
            return logged_in

        except Exception as e:
            console.print(f"[red]Erro durante login: {e}[/]")
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            return False

    def _extract_user_info(self, page: Page, platform: str) -> str:
        """Tenta extrair o nome/email do usuário logado."""
        try:
            if platform == "linkedin":
                # Tenta pegar o nome do perfil
                el = page.query_selector(".feed-identity-module__actor-meta a, .global-nav__me-photo")
                if el:
                    return el.get_attribute("alt") or el.inner_text().strip()
            elif platform == "gupy":
                el = page.query_selector("[data-testid='user-name'], .user-name")
                if el:
                    return el.inner_text().strip()
            # Fallback genérico: tenta pegar qualquer nome/email visível na nav
            for sel in [".user-name", ".user-email", "[data-testid*='user']", ".account-name"]:
                el = page.query_selector(sel)
                if el:
                    return el.inner_text().strip()[:80]
        except Exception:
            pass
        return ""

    # ─────────────────────────────────────────────────────────
    #  Criar contexto autenticado para candidatura
    # ─────────────────────────────────────────────────────────
    def create_authenticated_context(
        self, platform: str, headless: bool = False
    ) -> Optional[tuple]:
        """Cria um BrowserContext com a sessão salva da plataforma.
        
        Returns:
            Tuple de (playwright_instance, context, page) ou None se não houver sessão.
        """
        if not self.has_session(platform):
            return None

        session_file = self._session_file(platform)
        try:
            session_data = json.loads(session_file.read_text(encoding="utf-8"))
            storage_state = session_data.get("storage_state")
            if not storage_state:
                return None
        except Exception:
            return None

        state_dir = self._state_dir(platform)
        state_dir.mkdir(parents=True, exist_ok=True)

        pw = sync_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        try:
            # Tenta contexto persistente primeiro (mantém extensões, perfil)
            context = pw.chromium.launch_persistent_context(
                user_data_dir=str(state_dir),
                headless=headless,
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
                args=browser_args,
            )
        except Exception:
            # Fallback: contexto não-persistente com storage state injetado
            browser = pw.chromium.launch(headless=headless, args=browser_args)

            # Salva storage_state em arquivo temporário para o Playwright
            temp_state_file = SESSIONS_DIR / f"_temp_{platform}_state.json"
            temp_state_file.write_text(json.dumps(storage_state), encoding="utf-8")
            
            context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
                storage_state=str(temp_state_file),
            )

        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000)

        return (pw, context, page)

    # ─────────────────────────────────────────────────────────
    #  Verificar se sessão ainda é válida
    # ─────────────────────────────────────────────────────────
    def verify_session(self, platform: str) -> bool:
        """Abre o navegador headless e verifica se a sessão ainda está ativa."""
        if not self.has_session(platform):
            return False

        result = self.create_authenticated_context(platform, headless=True)
        if not result:
            return False

        pw, context, page = result
        info = PLATFORMS[platform]

        try:
            page.goto(info["check_url"], wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)

            # Verifica elemento de logado
            logged_el = page.query_selector(info["logged_in_selector"])
            if logged_el:
                return True

            # Verifica se redirecionou para login
            logout_el = page.query_selector(info["logged_out_indicator"])
            if logout_el:
                console.print(f"[yellow]⚠ Sessão do {info['name']} expirou. Faça login novamente.[/]")
                return False

            return True
        except Exception:
            return False
        finally:
            try:
                context.close()
                pw.stop()
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────
    #  Remoção de sessão
    # ─────────────────────────────────────────────────────────
    def remove_session(self, platform: str) -> bool:
        """Remove a sessão salva (logout)."""
        session_file = self._session_file(platform)
        if session_file.exists():
            session_file.unlink()
            console.print(f"[green]Sessão do {PLATFORMS.get(platform, {}).get('name', platform)} removida.[/]")
            return True
        return False
