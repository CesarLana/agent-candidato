"""LinkedIn Easy Apply — Candidatura rápida via conta logada.

Usa a sessão persistente do LinkedIn para:
1. Detectar vagas com botão "Easy Apply" / "Candidatura Simplificada"
2. Preencher o formulário multi-step do Easy Apply
3. Anexar currículo PDF
4. Submeter a candidatura

Se a vaga não tiver Easy Apply, redireciona para o fluxo externo padrão.
"""

import time
from pathlib import Path
from typing import Optional
from rich.console import Console

from automation.session_manager import SessionManager
from automation.form_mapper import FormMapper
from automation.safety_guard import SafetyGuard
from core.database import save_job, update_job_status
from core.llm import LLMEngine
from core.models import CandidateProfile, Job
from datetime import datetime

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent


class LinkedInApplier:
    """Candidatura via LinkedIn Easy Apply usando sessão autenticada."""

    def __init__(self, profile: CandidateProfile, headless: bool = False):
        self.profile = profile
        self.headless = headless
        self.session_mgr = SessionManager(headless=headless)
        self.safety_guard = SafetyGuard()
        self.llm = LLMEngine()
        self.mapper = FormMapper(profile, self.llm)

    def is_logged_in(self) -> bool:
        """Verifica se tem sessão válida do LinkedIn."""
        return self.session_mgr.has_session("linkedin")

    def login(self) -> bool:
        """Abre o navegador para o usuário fazer login no LinkedIn."""
        return self.session_mgr.interactive_login("linkedin")

    def apply(self, job: Job, auto_submit: bool = False, ignore_safety_hours: bool = False) -> bool:
        """Aplica para uma vaga do LinkedIn via Easy Apply.
        
        Args:
            job: Objeto Job com a URL da vaga
            auto_submit: Se True, submete sem confirmação
            ignore_safety_hours: Ignora restrição de horário comercial
            
        Returns:
            True se candidatura enviada com sucesso
        """
        # 🛡️ Verificação de Segurança Anti-Ban do LinkedIn
        can_apply, reason = self.safety_guard.can_apply_now("linkedin", ignore_hours=ignore_safety_hours)
        if not can_apply:
            console.print(f"\n[bold yellow]🛡️ Alerta de Segurança LinkedIn:[/] {reason}")
            import sys
            is_interactive = sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
            if is_interactive:
                override = console.input("[yellow]Deseja ignorar o alerta de segurança? (s/n): [/]").strip().lower()
                if override not in ["s", "sim", "y"]:
                    return False
            else:
                return False
        if not self.is_logged_in():
            console.print("[yellow]⚠ Você não está logado no LinkedIn.[/]")
            console.print("[cyan]Execute: python main.py login linkedin[/]")
            return False

        result = self.session_mgr.create_authenticated_context("linkedin", headless=self.headless)
        if not result:
            console.print("[red]❌ Não foi possível criar sessão autenticada.[/]")
            return False

        pw, context, page = result

        try:
            console.print(f"[bold cyan]🔗 Acessando vaga no LinkedIn:[/] {job.url}")
            page.goto(job.url, wait_until="domcontentloaded")
            time.sleep(3)

            # 1. Verificar se está logado
            if not self._check_logged_in(page):
                console.print("[red]❌ Sessão expirada. Faça login novamente.[/]")
                self.session_mgr.remove_session("linkedin")
                return False

            # 2. Verificar se a vaga tem Easy Apply
            easy_apply_btn = self._find_easy_apply_button(page)
            if not easy_apply_btn:
                console.print("[yellow]⚠ Esta vaga não tem Easy Apply. Redirecionando para candidatura externa...[/]")
                # Tenta clicar no botão de candidatura externa
                self._handle_external_apply(page, job)
                return False

            # 3. Clicar em Easy Apply
            console.print("[green]✓ Botão Easy Apply encontrado! Iniciando candidatura...[/]")
            easy_apply_btn.click()
            time.sleep(2)

            # 4. Preencher formulário multi-step do Easy Apply
            success = self._fill_easy_apply_form(page, job)

            if success:
                if auto_submit:
                    submitted = self._click_submit(page)
                    if submitted:
                        console.print("[bold green]🚀 Candidatura LinkedIn Easy Apply enviada com sucesso![/]")
                        self.safety_guard.record_application("linkedin", job.id)
                        update_job_status(job.id, "applied",
                                          applied_at=datetime.now().isoformat(),
                                          notes="Enviada via LinkedIn Easy Apply.",
                                          url=job.url)
                        return True
                else:
                    console.print("\n[bold yellow]⚠ REVISÃO: Verifique os campos na janela do navegador.[/]")
                    console.print("[dim]O formulário foi preenchido. Submeta manualmente ou pressione Enter.[/]")

                    import sys
                    is_interactive = sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty()
                    if is_interactive:
                        choice = console.input("[bold green]Enviar agora? (s/n): [/]").strip().lower()
                        if choice in ["s", "sim", "y"]:
                            submitted = self._click_submit(page)
                            if submitted:
                                console.print("[bold green]🚀 Candidatura enviada![/]")
                                self.safety_guard.record_application("linkedin", job.id)
                                update_job_status(job.id, "applied",
                                                  applied_at=datetime.now().isoformat(),
                                                  notes="Enviada via LinkedIn Easy Apply.",
                                                  url=job.url)
                                return True
                        else:
                            console.print("[yellow]Cancelada pelo usuário.[/]")
                            return False
                    else:
                        # Não-interativo: salva como revisado
                        update_job_status(job.id, "reviewed",
                                          notes="Easy Apply preenchido, aguardando envio manual.")
                        return True

            return False

        except Exception as e:
            console.print(f"[red]Erro durante Easy Apply: {e}[/]")
            return False
        finally:
            try:
                context.close()
                pw.stop()
            except Exception:
                pass

    def _check_logged_in(self, page) -> bool:
        """Verifica se o LinkedIn está autenticado."""
        try:
            selectors = [
                ".global-nav__me",
                "nav[aria-label='Primary']",
                ".feed-identity-module",
                "img.global-nav__me-photo",
            ]
            for sel in selectors:
                el = page.query_selector(sel)
                if el:
                    return True
            # Checa se redirecionou para login
            if "login" in page.url.lower() or "authwall" in page.url.lower():
                return False
            return True
        except Exception:
            return False

    def _find_easy_apply_button(self, page) -> Optional[object]:
        """Encontra o botão de Easy Apply na página da vaga."""
        selectors = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            "button:has-text('Candidatura simplificada')",
            "button:has-text('Candidatura Simplificada')",
            "button:has-text('Se candidatar')",
            "button[aria-label*='Easy Apply']",
            "button[aria-label*='Candidatura simplificada']",
            ".jobs-apply-button--top-card button",
            ".jobs-s-apply button",
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    text = el.inner_text().lower()
                    # Confirma que é Easy Apply (não "Apply" externo)
                    if any(w in text for w in ["easy", "simplificada", "candidatar", "apply"]):
                        return el
            except Exception:
                continue
        return None

    def _handle_external_apply(self, page, job: Job):
        """Lida com vagas que redirecionam para site externo."""
        try:
            external_btn = page.query_selector(
                "button:has-text('Apply'), a:has-text('Apply'), "
                "button:has-text('Candidatar'), a:has-text('Candidatar')"
            )
            if external_btn and external_btn.is_visible():
                href = external_btn.get_attribute("href")
                if href:
                    console.print(f"[cyan]→ URL externa: {href}[/]")
                    job.notes = f"Candidatura externa: {href}"
        except Exception:
            pass

    def _fill_easy_apply_form(self, page, job: Job) -> bool:
        """Preenche o formulário multi-step do LinkedIn Easy Apply."""
        max_steps = 8
        current_step = 0

        while current_step < max_steps:
            current_step += 1
            console.print(f"[dim]  Easy Apply - Etapa {current_step}...[/dim]")
            time.sleep(1)

            # Detecta o modal/dialog do Easy Apply
            modal = page.query_selector(
                ".jobs-easy-apply-modal, "
                ".jobs-easy-apply-content, "
                "[aria-label*='candidatura'], "
                "[role='dialog']"
            )
            if not modal:
                # Talvez já terminou
                break

            # a) Preencher campos de texto
            self._fill_text_inputs(page, job)

            # b) Preencher selects/dropdowns
            self._fill_selects(page, job)

            # c) Marcar checkboxes de consentimento
            self._handle_checkboxes(page)

            # d) Upload de currículo
            self._handle_resume_upload(page)

            # e) Preencher radio buttons
            self._handle_radio_buttons(page, job)

            # f) Verificar se tem botão "Next" / "Avançar" / "Review"
            next_btn = self._find_next_or_review(page)
            if next_btn:
                btn_text = next_btn.inner_text().strip().lower()
                if any(w in btn_text for w in ["review", "revis", "enviar", "submit"]):
                    # Chegamos à tela de revisão
                    console.print("[green]✓ Tela de revisão alcançada![/]")
                    next_btn.click()
                    time.sleep(2)
                    return True
                else:
                    next_btn.click()
                    time.sleep(2)
            else:
                # Verifica se o submit está visível (formulário de passo único)
                submit_btn = page.query_selector(
                    "button:has-text('Enviar candidatura'), "
                    "button:has-text('Submit application'), "
                    "button[aria-label*='Submit'], "
                    "button[aria-label*='Enviar']"
                )
                if submit_btn and submit_btn.is_visible():
                    return True
                break

        return True

    def _fill_text_inputs(self, page, job: Job):
        """Preenche inputs de texto no formulário Easy Apply."""
        inputs = page.query_selector_all(
            ".jobs-easy-apply-modal input:not([type='hidden']):not([type='submit'])"
            ":not([type='file']):not([type='checkbox']):not([type='radio']), "
            ".jobs-easy-apply-modal textarea, "
            "[role='dialog'] input:not([type='hidden']):not([type='submit'])"
            ":not([type='file']):not([type='checkbox']):not([type='radio']), "
            "[role='dialog'] textarea"
        )
        
        for el in inputs:
            try:
                if not el.is_visible():
                    continue
                # Pula campos já preenchidos
                current_val = el.input_value() if el.evaluate("e => e.tagName") != "TEXTAREA" else el.inner_text()
                if current_val and len(current_val.strip()) > 0:
                    continue

                name = el.get_attribute("name") or ""
                inp_id = el.get_attribute("id") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria_label = el.get_attribute("aria-label") or ""

                # Label associado
                label_text = ""
                if inp_id:
                    lbl = page.query_selector(f"label[for='{inp_id}']")
                    if lbl:
                        label_text = lbl.inner_text().strip()
                
                # Tenta pegar label do parent fieldset/div
                if not label_text:
                    try:
                        parent = el.evaluate_handle("e => e.closest('.fb-dash-form-element, .jobs-easy-apply-form-section__grouping')")
                        if parent:
                            lbl_el = parent.query_selector("label, .fb-dash-form-element__label, span.t-14")
                            if lbl_el:
                                label_text = lbl_el.inner_text().strip()
                    except Exception:
                        pass

                field_info = {
                    "name": name, "id": inp_id,
                    "placeholder": placeholder, "aria_label": aria_label,
                    "label": label_text,
                }
                field_type = self.mapper.identify_field_type(field_info)
                value = self.mapper.get_value_for_field(field_type, label_text or name or placeholder, job)

                if value:
                    el.scroll_into_view_if_needed()
                    el.click()
                    el.fill("")
                    el.type(value, delay=30)
                    time.sleep(0.3)
            except Exception:
                continue

    def _fill_selects(self, page, job: Job):
        """Preenche dropdowns no Easy Apply."""
        selects = page.query_selector_all(
            ".jobs-easy-apply-modal select, [role='dialog'] select"
        )
        for sel in selects:
            try:
                if not sel.is_visible():
                    continue
                name = sel.get_attribute("name") or ""
                sel_id = sel.get_attribute("id") or ""
                label_text = ""
                if sel_id:
                    lbl = page.query_selector(f"label[for='{sel_id}']")
                    if lbl:
                        label_text = lbl.inner_text().strip()

                field_info = {"name": name, "id": sel_id, "label": label_text, "aria_label": ""}
                field_type = self.mapper.identify_field_type(field_info)
                target_val = self.mapper.get_value_for_field(field_type, label_text or name, job)

                if not target_val:
                    continue

                options = []
                for opt in sel.query_selector_all("option"):
                    val = opt.get_attribute("value") or ""
                    txt = opt.inner_text().strip()
                    if txt and val:
                        options.append({"value": val, "text": txt})

                best = self.mapper.find_best_select_option(options, target_val)
                if best:
                    sel.select_option(value=best)
                    time.sleep(0.3)
            except Exception:
                continue

    def _handle_checkboxes(self, page):
        """Marca checkboxes de consentimento."""
        checkboxes = page.query_selector_all(
            ".jobs-easy-apply-modal input[type='checkbox'], "
            "[role='dialog'] input[type='checkbox']"
        )
        for cb in checkboxes:
            try:
                if not cb.is_visible():
                    continue
                cb_id = cb.get_attribute("id") or ""
                label_text = ""
                if cb_id:
                    lbl = page.query_selector(f"label[for='{cb_id}']")
                    if lbl:
                        label_text = lbl.inner_text().lower()
                full_str = (label_text + " " + cb_id).lower()
                if any(w in full_str for w in ["terms", "termos", "consent", "agree", "lgpd", "privacy", "follow"]):
                    if not cb.is_checked():
                        cb.check()
            except Exception:
                continue

    def _handle_resume_upload(self, page):
        """Faz upload do currículo no Easy Apply."""
        file_inputs = page.query_selector_all(
            ".jobs-easy-apply-modal input[type='file'], "
            "[role='dialog'] input[type='file']"
        )
        if not file_inputs:
            return

        # Encontra o PDF do currículo
        resume_path = self.profile.documents.resume_pdf_path
        p = Path(resume_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if not p.exists():
            # Fallback: busca qualquer PDF na pasta data/
            candidates = list((BASE_DIR / "data").glob("*.pdf"))
            candidates += list((BASE_DIR / "config").glob("*.pdf"))
            if candidates:
                p = candidates[0]
            else:
                console.print("[yellow]⚠ Nenhum currículo PDF encontrado para upload.[/]")
                return

        for fi in file_inputs:
            try:
                fi.set_input_files(str(p))
                console.print(f"[green]✓ Currículo anexado: {p.name}[/]")
                break
            except Exception:
                continue

    def _handle_radio_buttons(self, page, job: Job):
        """Preenche radio buttons comuns (Sim/Não, experiência, etc.)."""
        # Detecta grupos de radio buttons
        fieldsets = page.query_selector_all(
            ".jobs-easy-apply-modal fieldset, "
            "[role='dialog'] fieldset, "
            ".fb-dash-form-element"
        )
        for fs in fieldsets:
            try:
                legend = fs.query_selector("legend, label, span.t-14, .fb-dash-form-element__label")
                if not legend:
                    continue
                question_text = legend.inner_text().strip().lower()

                radios = fs.query_selector_all("input[type='radio']")
                if not radios:
                    continue

                # Mapear perguntas comuns para respostas
                answer = self._get_radio_answer(question_text)
                if not answer:
                    continue

                for radio in radios:
                    try:
                        radio_label = ""
                        radio_id = radio.get_attribute("id")
                        if radio_id:
                            lbl = page.query_selector(f"label[for='{radio_id}']")
                            if lbl:
                                radio_label = lbl.inner_text().strip().lower()
                        radio_val = (radio.get_attribute("value") or "").lower()

                        if answer in radio_label or answer in radio_val:
                            if not radio.is_checked():
                                radio.check()
                            break
                    except Exception:
                        continue
            except Exception:
                continue

    def _get_radio_answer(self, question: str) -> Optional[str]:
        """Retorna a resposta padrão para perguntas comuns de radio button."""
        q = question.lower()

        # Autorização de trabalho
        if any(w in q for w in ["autorizado", "authorized", "legally", "trabalhar no"]):
            return "sim"
        # Precisa de visto/sponsorship
        if any(w in q for w in ["sponsor", "visto", "visa"]):
            return "não"
        # Tem experiência com X
        if any(w in q for w in ["experience with", "experiência com", "years of"]):
            return "sim"
        # Aceita trabalhar presencialmente
        if any(w in q for w in ["presencial", "on-site", "relocate", "mudança"]):
            return "sim"
        # PCD
        if any(w in q for w in ["deficiência", "disability", "pcd"]):
            return "não"
        # Veterano
        if any(w in q for w in ["veteran", "veterano"]):
            return "não"
        # Gênero
        if any(w in q for w in ["gender", "gênero"]):
            return "prefiro não"

        return None

    def _find_next_or_review(self, page):
        """Encontra o botão Next/Avançar/Review no Easy Apply."""
        selectors = [
            "button[aria-label='Continue to next step']",
            "button[aria-label='Avançar para a próxima etapa']",
            "button:has-text('Next')",
            "button:has-text('Avançar')",
            "button:has-text('Continue')",
            "button:has-text('Continuar')",
            "button:has-text('Review')",
            "button:has-text('Revisar')",
            "button:has-text('Enviar candidatura')",
            "button:has-text('Submit application')",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible() and btn.is_enabled():
                    return btn
            except Exception:
                continue
        return None

    def _click_submit(self, page) -> bool:
        """Clica no botão final de submissão."""
        selectors = [
            "button:has-text('Enviar candidatura')",
            "button:has-text('Submit application')",
            "button[aria-label*='Submit']",
            "button[aria-label*='Enviar']",
            "button:has-text('Submit')",
            "button:has-text('Enviar')",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    time.sleep(3)
                    # Verifica confirmação
                    confirm = page.query_selector(
                        ":text('candidatura enviada'), :text('application submitted'), "
                        ":text('sucesso'), :text('successfully')"
                    )
                    return True
            except Exception:
                continue
        return False
