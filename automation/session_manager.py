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

    def save_cookie_session(self, platform: str, cookie_value: str) -> Dict:
        """Salva uma sessão diretamente a partir do cookie principal (ex: li_at no LinkedIn)."""
        clean_val = cookie_value.strip().strip('"').strip("'")
        if not clean_val:
            return {"success": False, "message": "Cookie não informado."}

        info = PLATFORMS.get(platform)
        if not info:
            return {"success": False, "message": f"Plataforma '{platform}' desconhecida."}

        cookie_name = "li_at" if platform == "linkedin" else "session_token"
        domain = ".linkedin.com" if platform == "linkedin" else f".{info['domain']}"

        storage = {
            "cookies": [
                {
                    "name": cookie_name,
                    "value": clean_val,
                    "domain": domain,
                    "path": "/",
                    "expires": time.time() + (86400 * 30),
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                }
            ],
            "origins": []
        }

        session_data = {
            "platform": platform,
            "saved_at": datetime.now().isoformat(),
            "user_info": f"Cookie {cookie_name} Conectado",
            "cookies_count": 1,
            "storage_state": storage,
        }

        session_file = self._session_file(platform)
        session_file.write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"success": True, "message": f"Sessão do {info['name']} salva com sucesso via cookie!"}

    def login_with_credentials(self, platform: str, email: str, password: str) -> Dict:
        """Realiza o login automatizado em modo headless usando e-mail e senha."""
        if platform not in PLATFORMS:
            return {"success": False, "message": f"Plataforma '{platform}' não suportada."}

        info = PLATFORMS[platform]
        pw = sync_playwright().start()
        try:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                locale="pt-BR",
            )
            page = context.new_page()
            page.set_default_timeout(30000)

            if platform == "linkedin":
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
                page.fill("input#username", email)
                page.fill("input#password", password)
                page.click("button[type='submit']")
                page.wait_for_timeout(4000)

                # Verifica se entrou
                cookies = context.cookies()
                has_li_at = any(c.get("name") == "li_at" for c in cookies)

                if has_li_at:
                    storage = context.storage_state()
                    user_info = self._extract_user_info(page, platform) or email
                    session_data = {
                        "platform": platform,
                        "saved_at": datetime.now().isoformat(),
                        "user_info": user_info,
                        "cookies_count": len(storage.get("cookies", [])),
                        "storage_state": storage,
                    }
                    session_file = self._session_file(platform)
                    session_file.write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")
                    browser.close()
                    pw.stop()
                    return {"success": True, "message": f"Login no LinkedIn realizado com sucesso para {user_info}!"}

                # Verifica se há checkpoint / 2FA / Captcha
                cur_url = page.url.lower()
                if "checkpoint" in cur_url or "challenge" in cur_url:
                    browser.close()
                    pw.stop()
                    return {
                        "success": False,
                        "requires_2fa": True,
                        "message": "O LinkedIn solicitou verificação de duas etapas (2FA) ou captcha. Use a aba 'Conectar via Cookie li_at' ou faça login pelo terminal: python main.py login linkedin."
                    }

                # Erro de senha
                error_el = page.query_selector("#error-for-password, #error-for-username, .alert-content")
                err_msg = error_el.inner_text().strip() if error_el else "Credenciais incorretas ou acesso recusado pelo LinkedIn."
                browser.close()
                pw.stop()
                return {"success": False, "message": err_msg}

            browser.close()
            pw.stop()
            return {"success": False, "message": f"Login por credenciais diretas não disponível para {platform}. Use o cookie de sessão ou login pelo terminal."}
        except Exception as e:
            try:
                pw.stop()
            except Exception:
                pass
            return {"success": False, "message": f"Erro durante autenticação: {str(e)}"}

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

        self._playwright = sync_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1280,850",
        ]
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        try:
            # Lança uma instância isolada e visível do Chromium (sem travar diretórios ou colidir com Chrome aberto)
            browser = self._playwright.chromium.launch(
                headless=False,
                args=browser_args,
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
            )

            page = context.new_page()
            page.set_default_timeout(180000)  # 3 min timeout

            # Navega para a página de login
            page.goto(info["login_url"], wait_until="domcontentloaded")

            console.print("[bold cyan]⏳ Janela aberta. Faça seu login...[/] (detecção automática ativa)")
            max_wait = 300  # 5 minutos
            elapsed = 0
            logged_in = False

            while elapsed < max_wait:
                time.sleep(2)
                elapsed += 2

                # Se o usuário fechou a janela do navegador
                if page.is_closed():
                    console.print("[dim]Janela fechada pelo usuário. Verificando sessão...[/dim]")
                    break

                try:
                    cookies = context.cookies()
                    # 1. Checagem direta de cookies de autenticação
                    if platform == "linkedin" and any(c.get("name") == "li_at" for c in cookies):
                        logged_in = True
                        break
                    elif platform == "gupy" and any("auth" in c.get("name", "").lower() or "token" in c.get("name", "").lower() for c in cookies):
                        logged_in = True
                        break
                    elif any(c.get("name") in ["session_id", "auth_token", "logged_in"] for c in cookies):
                        logged_in = True
                        break

                    # 2. Checagem por elementos de tela
                    logged_in_el = page.query_selector(info["logged_in_selector"])
                    if logged_in_el:
                        logged_in = True
                        break

                    # 3. Mudança de URL para página autenticada
                    current_url = page.url.lower()
                    if any(w in current_url for w in ["/feed", "/dashboard", "/home", "area-candidato", "minhas-vagas"]):
                        logout_el = page.query_selector(info["logged_out_indicator"])
                        if not logout_el:
                            logged_in = True
                            break
                except Exception:
                    continue

                if elapsed % 15 == 0:
                    console.print(f"[dim]  ... aguardando login ({elapsed}s)...[/dim]")

            # Verificação final de cookies caso a janela tenha sido fechada
            try:
                cookies = context.cookies()
                if not logged_in:
                    if platform == "linkedin" and any(c.get("name") == "li_at" for c in cookies):
                        logged_in = True
                    elif platform == "gupy" and len(cookies) >= 4:
                        logged_in = True
            except Exception:
                pass

            if logged_in:
                console.print(f"[bold green]✅ Login no {info['name']} confirmado com sucesso![/]")
                user_info = self._extract_user_info(page, platform)

                storage = context.storage_state()
                session_data = {
                    "platform": platform,
                    "saved_at": datetime.now().isoformat(),
                    "user_info": user_info or "Sessão Ativa",
                    "cookies_count": len(storage.get("cookies", [])),
                    "storage_state": storage,
                }

                session_file = self._session_file(platform)
                session_file.write_text(json.dumps(session_data, ensure_ascii=False, indent=2), encoding="utf-8")

                console.print(f"[green]💾 Sessão persistente salva com {session_data['cookies_count']} cookies![/]")
                if user_info:
                    console.print(f"[cyan]👤 Usuário: {user_info}[/]")
            else:
                console.print(f"[yellow]⚠ Login no {info['name']} não detectado ou janela fechada antes de concluir.[/]")

            try:
                browser.close()
            except Exception:
                pass

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
            if page.is_closed():
                return ""
            if platform == "linkedin":
                el = page.query_selector(".feed-identity-module__actor-meta a, .global-nav__me-photo")
                if el:
                    return el.get_attribute("alt") or el.inner_text().strip()
            elif platform == "gupy":
                el = page.query_selector("[data-testid='user-name'], .user-name")
                if el:
                    return el.inner_text().strip()
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

        pw = sync_playwright().start()

        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ]
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

        try:
            browser = pw.chromium.launch(headless=headless, args=browser_args)
            context = browser.new_context(
                viewport={"width": 1280, "height": 850},
                user_agent=ua,
                locale="pt-BR",
                storage_state=storage_state,
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            return (pw, context, page)
        except Exception as e:
            console.print(f"[red]Erro ao criar contexto autenticado: {e}[/]")
            try:
                pw.stop()
            except Exception:
                pass
            return None

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
