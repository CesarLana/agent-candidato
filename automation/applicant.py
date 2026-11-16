"""Orquestrador da candidatura automatizada com validação humana (Human-in-the-Loop)."""

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console

from automation.browser_manager import BrowserManager
from automation.form_mapper import FormMapper
from automation.visual_agent import VisualFormAgent
from core.database import save_job, update_job_status
from core.llm import LLMEngine
from core.models import CandidateProfile, Job
from core.resume_tailor import ResumeTailor
from notifications.telegram_bot import TelegramNotifier

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent


class JobApplicant:
    def __init__(self, profile: CandidateProfile, headless: bool = False, tailor_resume: bool = True):
        self.profile = profile
        self.browser_manager = BrowserManager(headless=headless)
        self.llm = LLMEngine()
        self.mapper = FormMapper(profile, self.llm)
        self.tailor = ResumeTailor(profile, self.llm) if tailor_resume else None
        self.notifier = TelegramNotifier()
        self.visual_agent = VisualFormAgent(self.llm)
        self.typing_delay = int(os.getenv("TYPING_DELAY_MS", "20"))

    def run_application(self, job: Job, auto_submit: bool = False) -> bool:
        """Executa a navegação, preenchimento e fluxo de candidatura."""
        if job.id is None:
            job = save_job(job)

        console.print(f"[bold cyan]Iniciando navegador para a vaga:[/] [bold]{job.title}[/] @ [bold]{job.company}[/]")
        page = self.browser_manager.start()

        try:
            page.goto(job.url, wait_until="domcontentloaded")
            time.sleep(2)

            # Verifica se precisa clicar em 'Apply' ou 'Candidatar-se'
            self._handle_initial_apply_buttons(page)

            # Preenchimento em loop multi-etapas (suporta formulários com passos 1, 2, 3...)
            max_steps = 5
            current_step = 1
            filled_summary = {}

            while current_step <= max_steps:
                console.print(f"[dim]Processando etapa {current_step}...[/dim]")

                # 1. Preenchimento de inputs de texto e áreas de texto
                step_filled = self._fill_form_elements(page, job)
                filled_summary.update(step_filled)

                # 2. Preenchimento de seletores dropdown (<select>)
                select_summary = self._fill_select_elements(page, job)
                filled_summary.update(select_summary)

                # 3. Marcação de consentimento / termos (LGPD, privacidade)
                self._handle_consent_checkboxes(page)

                # 4. Upload do currículo (se houver campo de arquivo nesta etapa)
                self._handle_file_upload(page, job)

                # 5. Verifica se há um botão de "Avançar / Próximo"
                next_btn = self._find_next_button(page)
                if next_btn:
                    console.print(f"[cyan]→ Avançando da etapa {current_step} para a próxima...[/cyan]")
                    next_btn.click()
                    page.wait_for_timeout(2000)
                    current_step += 1
                else:
                    # Chegou à etapa final
                    break

            console.print("\n[bold green]✓ Todos os campos de todas as etapas foram preenchidos![/]")
            if filled_summary:
                console.print("[dim]Resumo dos campos preenchidos:[/dim]")
                for f_name, f_val in filled_summary.items():
                    val_str = str(f_val)[:60] + ("..." if len(str(f_val)) > 60 else "")
                    console.print(f"  • [yellow]{f_name}[/]: {val_str}")

            # Human-in-the-loop: Validação humana
            if not auto_submit:
                review_shot = self.browser_manager.take_screenshot(f"review_job_{job.id}.png")

                # Se o Telegram estiver configurado, envia os botões para aprovar pelo celular
                if self.notifier.is_configured:
                    console.print("\n[bold cyan]📱 Telegram Bot Detectado:[/] Enviando alerta com print e botões de aprovação para o seu celular...")
                    approved = self.notifier.request_approval_via_telegram(job, review_shot, timeout_seconds=90)
                    if approved:
                        success = self._click_submit_button(page)
                        if success:
                            console.print("[bold green]🚀 Candidatura enviada com sucesso após aprovação via Telegram![/]")
                            update_job_status(job.id, "applied", applied_at=datetime.now().isoformat(), notes="Aprovada via Telegram.", url=job.url)
                            conf_shot = self.browser_manager.take_screenshot(f"applied_job_{job.id}.png")
                            self.notifier.send_photo(conf_shot, caption="🎉 <b>Candidatura Enviada com Sucesso!</b>")
                            time.sleep(2)
                            return True
                    else:
                        console.print("[yellow]Candidatura cancelada ou expirada via Telegram.[/]")
                        update_job_status(job.id, "skipped", notes="Cancelada via Telegram.", url=job.url)
                        return False

                # Fallback para validação no terminal local
                console.print(
                    "\n[bold yellow]⚠️ MODO HUMAN-IN-THE-LOOP ATIVO:[/]"
                    "\nO navegador está aberto na sua tela. Revise os campos preenchidos."
                )
                choice = console.input(
                    "[bold green]Deseja que o agente submeta a candidatura agora? (s/n/m - 'm' para submeter manualmente): [/]"
                ).strip().lower()

                if choice in ["s", "sim", "y", "yes"]:
                    success = self._click_submit_button(page)
                    if success:
                        console.print("[bold green]🚀 Candidatura enviada com sucesso![/]")
                        update_job_status(job.id, "applied", applied_at=datetime.now().isoformat(), notes="Enviada automaticamente com aprovação.", url=job.url)
                        self.browser_manager.take_screenshot(f"applied_job_{job.id}.png")
                        time.sleep(3)
                        return True
                    else:
                        console.print("[yellow]Não foi possível localizar o botão de submit com certeza. Por favor, clique manualmente no navegador.[/]")
                        console.input("[dim]Pressione Enter após enviar manualmente para fechar...[/]")
                        update_job_status(job.id, "applied", applied_at=datetime.now().isoformat(), notes="Enviada manualmente.", url=job.url)
                        return True
                elif choice in ["m", "manual"]:
                    console.print("[cyan]Modo manual: Conclua a candidatura na janela do navegador.[/]")
                    console.input("[dim]Pressione Enter quando terminar para registrar e fechar o navegador...[/]")
                    update_job_status(job.id, "applied", applied_at=datetime.now().isoformat(), notes="Revisada e enviada manualmente.", url=job.url)
                    return True
                else:
                    console.print("[yellow]Candidatura cancelada pelo usuário.[/]")
                    update_job_status(job.id, "skipped", notes="Cancelada antes do envio.", url=job.url)
                    return False
            else:
                self._click_submit_button(page)
                update_job_status(job.id, "applied", applied_at=datetime.now().isoformat(), notes="Enviada no modo auto-submit.", url=job.url)
                self.browser_manager.take_screenshot(f"applied_job_{job.id}.png")
                console.print("[bold green]🚀 Candidatura enviada com sucesso no modo automático![/]")
                return True

        except Exception as e:
            console.print(f"[bold red]Erro durante automação de candidatura:[/] {e}")
            update_job_status(job.id, "failed", notes=str(e))
            self.browser_manager.take_screenshot("error_screenshot.png")
            return False
        finally:
            self.browser_manager.stop()

    def _handle_initial_apply_buttons(self, page):
        """Clica no botão de candidatar se o formulário estiver oculto em outra aba/modal."""
        selectors = [
            "a[href*='#app']",
            "a[href*='apply']",
            "button:has-text('Apply')",
            "button:has-text('Candidatar')",
            "a:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            ".postings-btn",
        ]
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    page.wait_for_timeout(1500)
                    break
            except Exception:
                continue

    def _fill_form_elements(self, page, job: Job) -> Dict[str, str]:
        filled = {}
        inputs = page.query_selector_all("input:not([type='hidden']):not([type='submit']):not([type='file']), textarea")

        for el in inputs:
            try:
                if not el.is_visible():
                    continue

                # Coleta metadados do campo
                name = el.get_attribute("name") or ""
                inp_id = el.get_attribute("id") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria_label = el.get_attribute("aria-label") or ""

                # Tenta pegar texto do label associado
                label_text = ""
                if inp_id:
                    label_el = page.query_selector(f"label[for='{inp_id}']")
                    if label_el:
                        label_text = label_el.inner_text().strip()

                field_info = {
                    "name": name,
                    "id": inp_id,
                    "placeholder": placeholder,
                    "aria_label": aria_label,
                    "label": label_text,
                }

                field_type = self.mapper.identify_field_type(field_info)
                value = self.mapper.get_value_for_field(field_type, label_text or name or placeholder, job)

                if value:
                    el.scroll_into_view_if_needed()
                    el.click()
                    # Limpa e digita com intervalo suave
                    el.fill("")
                    el.type(value, delay=self.typing_delay)
                    filled[label_text or name or inp_id or field_type] = value
                    page.wait_for_timeout(200)

            except Exception:
                continue

        return filled

    def _fill_select_elements(self, page, job: Job) -> Dict[str, str]:
        """Preenche elementos <select> dropdown selecionando a melhor opção."""
        filled = {}
        selects = page.query_selector_all("select")

        for sel in selects:
            try:
                if not sel.is_visible():
                    continue

                name = sel.get_attribute("name") or ""
                sel_id = sel.get_attribute("id") or ""
                aria_label = sel.get_attribute("aria-label") or ""

                label_text = ""
                if sel_id:
                    lbl = page.query_selector(f"label[for='{sel_id}']")
                    if lbl:
                        label_text = lbl.inner_text().strip()

                field_info = {
                    "name": name,
                    "id": sel_id,
                    "aria_label": aria_label,
                    "label": label_text,
                }
                field_type = self.mapper.identify_field_type(field_info)
                target_val = self.mapper.get_value_for_field(field_type, label_text or name, job)

                if not target_val:
                    continue

                # Coleta as opções disponíveis
                options_data = []
                opt_elements = sel.query_selector_all("option")
                for opt in opt_elements:
                    val = opt.get_attribute("value") or ""
                    txt = opt.inner_text().strip()
                    if txt and val:
                        options_data.append({"value": val, "text": txt})

                best_val = self.mapper.find_best_select_option(options_data, target_val)
                if best_val:
                    sel.select_option(value=best_val)
                    filled[label_text or name or sel_id] = target_val
                    page.wait_for_timeout(200)

            except Exception:
                continue

        return filled

    def _handle_consent_checkboxes(self, page):
        """Marca automaticamente caixas de consentimento de privacidade e termos da vaga."""
        checkboxes = page.query_selector_all("input[type='checkbox']")
        for cb in checkboxes:
            try:
                if not cb.is_visible():
                    continue
                # Verifica texto de label ou id associado
                cb_id = cb.get_attribute("id") or ""
                name = cb.get_attribute("name") or ""
                label_text = ""
                if cb_id:
                    lbl = page.query_selector(f"label[for='{cb_id}']")
                    if lbl:
                        label_text = lbl.inner_text().lower()

                full_str = (label_text + " " + name + " " + cb_id).lower()
                if any(w in full_str for w in ["lgpd", "consent", "termos", "terms", "privacy", "privacidade", "agree", "concordo", "aceito"]):
                    if not cb.is_checked():
                        cb.check()
            except Exception:
                continue

    def _handle_file_upload(self, page, job: Job):
        """Encontra campos de input file para o currículo e faz o upload (customizado se ativado)."""
        pdf_to_upload: Optional[Path] = None

        # Tenta gerar currículo sob medida se a engine estiver ativa
        if self.tailor:
            try:
                console.print("[dim]Gerando currículo ATS sob medida para esta vaga...[/dim]")
                pdf_to_upload = self.tailor.generate_tailored_pdf(job)
            except Exception as e:
                console.print(f"[yellow]Aviso: Falha ao gerar currículo customizado ({e}). Usando currículo padrão.[/yellow]")

        if not pdf_to_upload or not pdf_to_upload.exists():
            resume_path = self.profile.documents.resume_pdf_path
            p = Path(resume_path)
            if not p.is_absolute():
                p = BASE_DIR / p

            if not p.exists():
                candidates = list((BASE_DIR / "data").glob("*.pdf")) + list((BASE_DIR / "data").glob("*.txt"))
                if candidates:
                    pdf_to_upload = candidates[0]
                else:
                    return
            else:
                pdf_to_upload = p

        file_inputs = page.query_selector_all("input[type='file']")
        for f_input in file_inputs:
            try:
                f_input.set_input_files(str(pdf_to_upload))
                console.print(f"[green]✓ Currículo anexado:[/] [bold]{pdf_to_upload.name}[/bold]")
                break
            except Exception:
                continue

    def _find_next_button(self, page):
        """Encontra botões de navegação para a próxima etapa (Avançar/Next/Continuar)."""
        selectors = [
            "button:has-text('Avançar')",
            "button:has-text('Próximo')",
            "button:has-text('Proximo')",
            "button:has-text('Continuar')",
            "button:has-text('Next')",
            "button:has-text('Continue')",
            "button[data-testid='next-step-button']",
            "button[aria-label*='Next']",
            "button[aria-label*='Avançar']",
            "a:has-text('Avançar')",
            "a:has-text('Next')",
        ]
        # Palavras proibidas para não confundir 'Next' com 'Submit'
        forbidden = ["finalizar", "concluir", "enviar", "submit"]

        for sel in selectors:
            try:
                elements = page.query_selector_all(sel)
                for el in elements:
                    if el.is_visible() and el.is_enabled():
                        txt = el.inner_text().lower().strip()
                        if not any(f in txt for f in forbidden):
                            return el
            except Exception:
                continue
        return None

    def _click_submit_button(self, page) -> bool:
        """Tenta encontrar e clicar no botão final de submissão."""
        selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Submit Application')",
            "button:has-text('Enviar Candidatura')",
            "button:has-text('Submit')",
            "button:has-text('Enviar')",
            "#submit_app",
            "#apply_button",
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(3000)
                    return True
            except Exception:
                continue

        # Fallback de visão multimodal caso o botão use classes não convencionais
        try:
            elements = self.visual_agent.annotate_interactive_elements(page)
            chosen_id = self.visual_agent.find_element_by_vision(
                page, "botão de enviar ou submeter candidatura", elements
            )
            self.visual_agent.remove_annotations(page)
            if chosen_id:
                target_data = next((e for e in elements if e["id"] == chosen_id), None)
                if target_data:
                    page.mouse.click(target_data["x"], target_data["y"])
                    page.wait_for_timeout(3000)
                    return True
        except Exception:
            pass

        return False
