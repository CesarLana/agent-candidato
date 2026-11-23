"""Motor de personalização e geração de currículo sob medida para ATS (Tailored Resume).

Utiliza ReportLab para gerar PDFs instantâneos, elegantes e 100% compatíveis com
softwares de triagem e parsing de ATS (sem tabelas aninhadas complexas, texto selecionável).
"""

import html
import re
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.llm import LLMEngine
from core.models import CandidateProfile, Job

BASE_DIR = Path(__file__).resolve().parent.parent


class ResumeTailor:
    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def generate_tailored_pdf(self, job: Job, output_path: Optional[Path] = None) -> Path:
        """Gera um PDF sob medida para a vaga em fração de segundo."""
        if not output_path:
            clean_company = re.sub(r"[^a-zA-Z0-9_-]", "_", job.company.lower())
            clean_title = re.sub(r"[^a-zA-Z0-9_-]", "_", job.title.lower())[:25]
            filename = f"curriculo_{clean_company}_{clean_title}.pdf"
            output_path = BASE_DIR / "data" / filename

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Customização do Resumo Profissional para a vaga
        tailored_summary = self._tailor_summary(job)

        # 2. Priorização de Habilidades (Skills em comum no topo)
        ordered_skills = self._order_skills(job)

        # 3. Compilação do PDF via ReportLab
        try:
            self._build_pdf(job, tailored_summary, ordered_skills, output_path)
        except PermissionError:
            # Se o arquivo estiver aberto em outro processo (leitor de PDF no Windows), gera com sufixo
            import time
            alt_filename = f"{output_path.stem}_{int(time.time())}.pdf"
            output_path = output_path.parent / alt_filename
            self._build_pdf(job, tailored_summary, ordered_skills, output_path)

        return output_path

    def _is_english_job(self, job: Job) -> bool:
        """Detecta se a vaga está predominantemente em inglês."""
        text = (job.title + " " + (job.description or "")[:2000]).lower()
        en_indicators = [
            "requirements", "responsibilities", "skills", "experience", "we are looking",
            "about the role", "benefits", "engineer", "developer", "software", "backend",
            "frontend", "team", "years", "qualification", "must have", "full-time"
        ]
        pt_indicators = [
            "requisitos", "responsabilidades", "habilidades", "experiência", "procuramos",
            "sobre a vaga", "benefícios", "desenvolvedor", "engenheiro", "atuar", "equipe",
            "anos", "diferencial", "conhecimento", "vaga"
        ]
        en_count = sum(1 for w in en_indicators if w in text)
        pt_count = sum(1 for w in pt_indicators if w in text)
        return en_count > pt_count

    def _tailor_summary(self, job: Job) -> str:
        """Adapta o resumo profissional com palavras-chave relevantes da vaga."""
        is_english = self._is_english_job(job)
        lang_instruction = "em inglês profissional fluente (para sistemas ATS globais)" if is_english else "em português do Brasil"
        prompt = f"""
Você é um especialista em otimização de currículos para sistemas ATS (Applicant Tracking Systems).
Reescreva o resumo profissional do candidato abaixo para que ele se destaque com máxima relevância para a vaga pretendida.

Vaga: {job.title} na {job.company}
Descrição da vaga: {job.description[:2500]}

Perfil do Candidato:
Resumo original: {self.profile.professional_summary}
Habilidades: {', '.join(self.profile.skills.primary)}
Experiências: {', '.join([f'{e.role} na {e.company}' for e in self.profile.experiences])}

Diretrizes:
- Destaque as tecnologias e experiências que coincidem com os requisitos da vaga.
- Escreva em 1 parágrafo fluido, confiante e profissional ({lang_instruction}).
- Limite de 3 a 5 linhas.
"""
        custom_summary = self.llm._generate_raw(prompt)
        if custom_summary:
            return custom_summary.strip()

        return (self.profile.professional_summary or "").strip()

    def _order_skills(self, job: Job) -> dict:
        """Organiza as habilidades colocando primeiro as mais relevantes para a vaga."""
        job_text = (job.title + " " + job.description).lower()

        primary = []
        secondary = []

        for s in self.profile.skills.primary:
            if s.lower() in job_text:
                primary.insert(0, s)
            else:
                primary.append(s)

        for s in self.profile.skills.secondary:
            if s.lower() in job_text:
                primary.append(s)
            else:
                secondary.append(s)

        return {"primary": primary, "secondary": secondary}

    def _build_pdf(self, job: Job, summary: str, skills: dict, output_path: Path):
        """Monta o documento PDF com formatação limpa e tipografia nítida."""
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            leftMargin=36,
            rightMargin=36,
            topMargin=36,
            bottomMargin=36,
        )

        styles = getSampleStyleSheet()

        # Estilos customizados
        name_style = ParagraphStyle(
            "NameStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=18,
            leading=22,
            textColor=colors.HexColor("#0f172a"),
            textTransform="uppercase",
        )

        target_style = ParagraphStyle(
            "TargetStyle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=colors.HexColor("#2563eb"),
        )

        contact_style = ParagraphStyle(
            "ContactStyle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#475569"),
        )

        section_title_style = ParagraphStyle(
            "SectionTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=colors.HexColor("#1e3a8a"),
            spaceBefore=6,
            spaceAfter=2,
            textTransform="uppercase",
        )

        body_style = ParagraphStyle(
            "Body",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12.5,
            textColor=colors.HexColor("#1e293b"),
            alignment=4,  # Justificado
        )

        job_title_style = ParagraphStyle(
            "JobTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=12,
            textColor=colors.HexColor("#0f172a"),
        )

        job_meta_style = ParagraphStyle(
            "JobMeta",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#2563eb"),
        )

        period_style = ParagraphStyle(
            "Period",
            parent=styles["Normal"],
            fontName="Helvetica-Oblique",
            fontSize=8.5,
            leading=11,
            textColor=colors.HexColor("#64748b"),
            alignment=2,  # Direita
        )

        story = []

        # Cabeçalho
        p = self.profile.personal_info
        links = self.profile.links
        full_name = p.full_name or p.first_name

        story.append(Paragraph(html.escape(full_name), name_style))
        story.append(Paragraph(html.escape(job.title), target_style))
        story.append(Spacer(1, 4))

        # Barra de Contatos
        contact_parts = []
        if p.email:
            contact_parts.append(html.escape(p.email))
        if p.phone:
            contact_parts.append(html.escape(p.phone))
        if p.city or p.state:
            contact_parts.append(html.escape(f"{p.city}, {p.state}".strip(", ")))
        if links.linkedin:
            clean_in = links.linkedin.replace("https://www.linkedin.com/in/", "").replace("https://linkedin.com/in/", "")
            contact_parts.append(f"linkedin.com/in/{html.escape(clean_in)}")
        if links.github:
            clean_gh = links.github.replace("https://github.com/", "")
            contact_parts.append(f"github.com/{html.escape(clean_gh)}")

        story.append(Paragraph(" | ".join(contact_parts), contact_style))
        story.append(Spacer(1, 6))
        story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#2563eb"), spaceAfter=8))

        is_english = self._is_english_job(job)

        # 1. Resumo Profissional
        sec_summary = "Professional Summary" if is_english else "Resumo Profissional"
        story.append(Paragraph(sec_summary, section_title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))
        story.append(Paragraph(html.escape(summary), body_style))
        story.append(Spacer(1, 6))

        # 2. Competências Técnicas
        sec_skills = "Technical Skills" if is_english else "Competências Técnicas"
        story.append(Paragraph(sec_skills, section_title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))

        prefix_prim = "<b>Core Skills:</b> " if is_english else "<b>Principais:</b> "
        prim_str = prefix_prim + ", ".join(skills["primary"][:10])
        story.append(Paragraph(prim_str, body_style))

        if skills["secondary"]:
            prefix_sec = "<b>Additional Tools:</b> " if is_english else "<b>Outras Ferramentas:</b> "
            sec_str = prefix_sec + ", ".join(skills["secondary"][:8])
            story.append(Paragraph(sec_str, body_style))
        story.append(Spacer(1, 6))

        # 3. Experiência Profissional
        sec_exp = "Professional Experience" if is_english else "Experiência Profissional"
        story.append(Paragraph(sec_exp, section_title_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))

        for exp in self.profile.experiences:
            header_table = Table(
                [
                    [
                        Paragraph(f"<b>{html.escape(exp.role)}</b>", job_title_style),
                        Paragraph(html.escape(exp.period), period_style),
                    ],
                    [
                        Paragraph(html.escape(exp.company), job_meta_style),
                        Paragraph("", period_style),
                    ],
                ],
                colWidths=[380, 140],
            )
            header_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ("TOPPADDING", (0, 0), (-1, -1), 0),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                    ]
                )
            )
            story.append(header_table)
            story.append(Paragraph(html.escape(exp.description), body_style))
            story.append(Spacer(1, 6))

        # 4. Formação e Idiomas
        faq = self.profile.faq_answers
        if faq.get("education_level") or faq.get("english_level"):
            sec_edu = "Education & Languages" if is_english else "Formação e Idiomas"
            story.append(Paragraph(sec_edu, section_title_style))
            story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1"), spaceAfter=4))

            extra_lines = []
            if faq.get("education_level"):
                edu_prefix = "<b>Education:</b> " if is_english else "<b>Formação:</b> "
                extra_lines.append(f"{edu_prefix}{html.escape(faq['education_level'])}")
            if faq.get("english_level"):
                lang_str = f"<b>English:</b> {html.escape(faq['english_level'])} | <b>Portuguese:</b> Native" if is_english else f"<b>Inglês:</b> {html.escape(faq['english_level'])} | <b>Português:</b> Nativo"
                extra_lines.append(lang_str)

            story.append(Paragraph(" &bull; ".join(extra_lines), body_style))

        doc.build(story)
