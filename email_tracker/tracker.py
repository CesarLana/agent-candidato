"""Rastreador de respostas de recrutadores e convites de entrevista via E-mail (IMAP).

Varre a caixa de entrada em busca de retornos de processos seletivos,
classifica as mensagens usando IA (Entrevista, Rejeição, Confirmação) e atualiza o funil.
"""

import email
from email.header import decode_header
import imaplib
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console

from core.database import list_jobs, update_job_status
from core.llm import LLMEngine
from core.models import Job
from notifications.telegram_bot import TelegramNotifier

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent


class EmailFeedbackTracker:
    def __init__(self):
        self.imap_host = os.getenv("EMAIL_IMAP_HOST", "imap.gmail.com")
        self.email_user = os.getenv("EMAIL_USER", "").strip()
        self.email_password = os.getenv("EMAIL_PASSWORD", "").strip() # Senha de app
        self.llm = LLMEngine()
        self.notifier = TelegramNotifier()

    @property
    def is_configured(self) -> bool:
        return bool(self.email_user and self.email_password)

    def _decode_header_str(self, header_val: str) -> str:
        """Decodifica cabeçalhos RFC 2047 do e-mail."""
        if not header_val:
            return ""
        decoded_fragments = decode_header(header_val)
        result = []
        for frag, enc in decoded_fragments:
            if isinstance(frag, bytes):
                try:
                    result.append(frag.decode(enc or "utf-8", errors="ignore"))
                except Exception:
                    result.append(frag.decode("latin1", errors="ignore"))
            else:
                result.append(str(frag))
        return "".join(result)

    def fetch_recent_recruitment_emails(self, days: int = 15) -> List[Dict[str, str]]:
        """Conecta ao servidor IMAP e busca e-mails relacionados a recrutamento."""
        if not self.is_configured:
            return []

        recruitment_emails = []
        try:
            mail = imaplib.IMAP4_SSL(self.imap_host)
            mail.login(self.email_user, self.email_password)
            mail.select("INBOX", readonly=True)

            since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, f'(SINCE "{since_date}")')

            if status != "OK" or not messages[0]:
                mail.logout()
                return []

            email_ids = messages[0].split()
            # Limita aos últimos 50 e-mails para não sobrecarregar
            for e_id in reversed(email_ids[-50:]):
                try:
                    res, msg_data = mail.fetch(e_id, "(RFC822)")
                    if res != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    subject = self._decode_header_str(msg.get("Subject", ""))
                    sender = self._decode_header_str(msg.get("From", ""))
                    date_str = msg.get("Date", "")

                    # Filtro preliminar de relevância por palavras-chave
                    text_to_check = (subject + " " + sender).lower()
                    keywords = [
                        "vaga", "candidatura", "entrevista", "interview", "gupy",
                        "greenhouse", "lever", "workable", "recrutamento", "processo seletivo",
                        "application", "applied", "talent", "carreira"
                    ]
                    if not any(k in text_to_check for k in keywords):
                        continue

                    # Extrai corpo do e-mail
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            if ctype == "text/plain":
                                body = part.get_payload(decode=True).decode(errors="ignore")
                                break
                            elif ctype == "text/html" and not body:
                                body = part.get_payload(decode=True).decode(errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")

                    recruitment_emails.append({
                        "sender": sender,
                        "subject": subject,
                        "date": date_str,
                        "body": body[:2000],
                    })
                except Exception:
                    continue

            mail.logout()
        except Exception as e:
            console.print(f"[yellow]Aviso ao conectar ao servidor de e-mail:[/] {e}")

        return recruitment_emails

    def classify_email(self, subject: str, body: str) -> Dict[str, str]:
        """Classifica a mensagem com IA em: interview, rejected, received, offer."""
        prompt = f"""
Você é um classificador de e-mails de recrutamento e recursos humanos.
Analise a mensagem abaixo recebida por um candidato:

Assunto: {subject}
Corpo do e-mail:
{body[:1500]}

Classifique a mensagem estritamente em uma das seguintes categorias:
1. "interview": A empresa está convidando ou agendando entrevista, bate-papo técnico ou dinâmica.
2. "rejected": A empresa agradeceu mas informou que não seguirá com a candidatura no momento.
3. "received": Apenas confirmação de que a candidatura foi recebida / está em análise.
4. "offer": Proposta formal de contratação ou oferta salarial.
5. "other": E-mail genérico, newsletter ou não relacionado a feedback.

Responda ESTRITAMENTE em formato JSON com o seguinte schema:
{{
  "category": "interview" | "rejected" | "received" | "offer" | "other",
  "company_detected": "<Nome da empresa identificada ou ''>",
  "summary": "<1 frase resumindo o status para o candidato>"
}}
"""
        ans = self.llm._generate_raw(prompt)
        if ans:
            try:
                match = re.search(r"\{.*\}", ans, re.DOTALL)
                if match:
                    return json.loads(match.group(0))
            except Exception:
                pass

        # Fallback heurístico
        text_lower = (subject + " " + body).lower()
        if any(w in text_lower for w in ["entrevista", "bate-papo", "interview", "agendar", "conversar", "calendly"]):
            return {"category": "interview", "company_detected": "", "summary": "Possível convite para entrevista detectado!"}
        if any(w in text_lower for w in ["não seguiremos", "nao seguiremos", "outro perfil", "banco de talentos", "infelizmente", "regret to inform"]):
            return {"category": "rejected", "company_detected": "", "summary": "Candidatura não selecionada."}
        if any(w in text_lower for w in ["recebemos", "confirmamos", "sucesso", "application received"]):
            return {"category": "received", "company_detected": "", "summary": "Candidatura recebida e em análise."}

        return {"category": "other", "company_detected": "", "summary": "E-mail informativo."}

    def sync_feedback(self) -> Dict[str, int]:
        """Varre os e-mails, classifica e atualiza as vagas no banco de dados."""
        console.print("[bold cyan]📬 Sincronizando retornos de processos seletivos por e-mail...[/]")
        emails = self.fetch_recent_recruitment_emails()

        stats = {"interview": 0, "rejected": 0, "received": 0, "offer": 0}
        all_jobs = list_jobs()

        for em in emails:
            classification = self.classify_email(em["subject"], em["body"])
            cat = classification.get("category")
            if cat in stats:
                stats[cat] += 1

            # Tenta encontrar vaga correspondente no banco
            comp = classification.get("company_detected", "").lower()
            matched_job = None
            for j in all_jobs:
                if (comp and comp in j.company.lower()) or (j.company.lower() in (em["sender"] + " " + em["subject"]).lower()):
                    matched_job = j
                    break

            if matched_job:
                new_status = cat if cat in ["interview", "rejected", "offer"] else matched_job.status
                update_job_status(matched_job.id, new_status, notes=classification.get("summary"))
                console.print(f"  • [yellow]{matched_job.company}[/]: Status atualizado para [bold]{new_status.upper()}[/] ({classification.get('summary')})")

                # Alerta prioritário no Telegram para entrevistas e ofertas
                if cat in ["interview", "offer"] and self.notifier.is_configured:
                    self.notifier.send_message(
                        f"🎉 <b>BOAS NOTÍCIAS!</b>\n\n"
                        f"Você recebeu um retorno importante da empresa <b>{matched_job.company}</b>!\n"
                        f"<b>Vaga:</b> {matched_job.title}\n"
                        f"<b>Status:</b> {new_status.upper()}\n"
                        f"<b>Mensagem:</b> {classification.get('summary')}\n\n"
                        f"<i>Verifique sua caixa de entrada ({em['subject']}).</i>"
                    )

        return stats
