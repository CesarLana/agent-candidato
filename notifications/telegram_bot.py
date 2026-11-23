"""Módulo de integração com o Telegram para notificações e aprovação remota."""

import html
import json
import os
import time
from pathlib import Path
from typing import Optional
import requests

from core.models import Job

BASE_DIR = Path(__file__).resolve().parent.parent


class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        self.base_url = f"https://api.telegram.org/bot{self.token}" if self.token else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id and self.token != "seu_token_aqui")

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Envia mensagem de texto para o chat configurado."""
        if not self.is_configured:
            return False
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": False,
            }
            resp = requests.post(url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception:
            return False

    def send_photo(self, photo_path: Path, caption: str = "") -> bool:
        """Envia uma imagem (screenshot do formulário) para o Telegram."""
        if not self.is_configured or not photo_path.exists():
            return False
        try:
            url = f"{self.base_url}/sendPhoto"
            with open(photo_path, "rb") as f:
                files = {"photo": f}
                data = {"chat_id": self.chat_id, "caption": caption[:1024], "parse_mode": "HTML"}
                resp = requests.post(url, data=data, files=files, timeout=15)
                return resp.status_code == 200
        except Exception:
            return False

    def send_document(self, doc_path: Path, caption: str = "") -> bool:
        """Envia um documento (PDF do currículo customizado) para o Telegram."""
        if not self.is_configured or not doc_path.exists():
            return False
        try:
            url = f"{self.base_url}/sendDocument"
            with open(doc_path, "rb") as f:
                files = {"document": f}
                data = {"chat_id": self.chat_id, "caption": caption[:1024]}
                resp = requests.post(url, data=data, files=files, timeout=20)
                return resp.status_code == 200
        except Exception:
            return False

    def notify_job_found(self, job: Job, pdf_path: Optional[Path] = None):
        """Envia um resumo completo da vaga e o currículo gerado."""
        if not self.is_configured:
            return

        score = job.fit_score or 0
        blocks = int(round(score / 10))
        bar = "🟩" * blocks + "⬜" * (10 - blocks)

        esc_title = html.escape(job.title or "Vaga")
        esc_company = html.escape(job.company or "Empresa")
        esc_location = html.escape(job.location or "Não especificado")
        esc_workplace = html.escape(job.workplace_type or "Remoto")
        esc_summary = html.escape(job.fit_summary or "Sem resumo disponível.")

        matched_skills = html.escape(", ".join(job.skills_matched) if job.skills_matched else "Competências gerais")
        missing_skills = html.escape(", ".join(job.skills_missing) if job.skills_missing else "Nenhum gap crítico")

        msg = (
            f"🎯 <b>NOVA VAGA ENCONTRADA!</b>\n\n"
            f"💼 <b>Cargo:</b> {esc_title}\n"
            f"🏢 <b>Empresa:</b> {esc_company}\n"
            f"📍 <b>Local / Modalidade:</b> {esc_location} ({esc_workplace})\n"
            f"📊 <b>Fit Score:</b> {score}% {bar}\n\n"
            f"✅ <b>Skills Alinhadas:</b> {matched_skills}\n"
            f"⚠️ <b>Gaps / Desenvolver:</b> {missing_skills}\n\n"
            f"💡 <b>Diagnóstico:</b>\n<i>{esc_summary}</i>\n\n"
            f"🔗 <a href='{job.url}'>Ver anúncio original</a>"
        )
        self.send_message(msg)

        if pdf_path and pdf_path.exists():
            self.send_document(pdf_path, caption=f"📄 Currículo sob medida para {job.company}")

    def request_approval_via_telegram(
        self, job: Job, screenshot_path: Optional[Path] = None, timeout_seconds: int = 120
    ) -> bool:
        """Envia o print do formulário preenchido com botões inline de aprovação e aguarda a resposta."""
        if not self.is_configured:
            return False

        esc_title = html.escape(job.title or "Vaga")
        esc_company = html.escape(job.company or "Empresa")

        # Envia a screenshot do formulário
        if screenshot_path and screenshot_path.exists():
            self.send_photo(screenshot_path, caption=f"📸 Formulário preenchido para <b>{esc_title}</b> na <b>{esc_company}</b>")

        # Cria botões inline para o usuário clicar
        callback_approve = f"appr_{job.id or 1}"
        callback_reject = f"rej_{job.id or 1}"

        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🚀 Aprovar & Enviar", "callback_data": callback_approve},
                    {"text": "❌ Cancelar / Pular", "callback_data": callback_reject},
                ]
            ]
        }

        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": (
                f"⚠️ <b>Confirmação de Envio ({timeout_seconds}s para responder):</b>\n\n"
                f"Revise os dados e o print acima.\n"
                f"Deseja submeter a candidatura para <b>{esc_title}</b> @ <b>{esc_company}</b>?"
            ),
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code != 200:
                return False

            msg_data = resp.json()
            message_id = msg_data.get("result", {}).get("message_id")

            # Aguarda a resposta (polling nos updates)
            start_time = time.time()
            last_update_id = 0

            # Descarta updates antigos
            updates_resp = requests.get(f"{self.base_url}/getUpdates", params={"offset": -1}, timeout=5)
            if updates_resp.status_code == 200:
                results = updates_resp.json().get("result", [])
                if results:
                    last_update_id = results[-1]["update_id"] + 1

            while time.time() - start_time < timeout_seconds:
                poll_resp = requests.get(
                    f"{self.base_url}/getUpdates",
                    params={"offset": last_update_id, "timeout": 2},
                    timeout=5,
                )
                if poll_resp.status_code == 200:
                    for upd in poll_resp.json().get("result", []):
                        last_update_id = upd["update_id"] + 1
                        cb = upd.get("callback_query")
                        if cb and cb.get("data") in [callback_approve, callback_reject]:
                            # Confirma recebimento da ação
                            requests.post(
                                f"{self.base_url}/answerCallbackQuery",
                                json={"callback_query_id": cb["id"]},
                                timeout=5,
                            )

                            if cb["data"] == callback_approve:
                                self.send_message("✅ <b>Candidatura aprovada pelo usuário!</b> Enviando...")
                                return True
                            else:
                                self.send_message("🛑 <b>Candidatura cancelada pelo usuário.</b>")
                                return False

                time.sleep(1)

            self.send_message("⏳ <b>Tempo limite de aprovação esgotado.</b> Candidatura cancelada por segurança.")
            return False

        except Exception:
            return False
