"""Scanner e Simulador de Compatibilidade ATS (Applicant Tracking System).

Inspirado em projetos como Resume-Matcher e Applied:
Analisa a estrutura do currículo do candidato (PDF ou dados do perfil) contra
a descrição detalhada da vaga para diagnosticar a probabilidade de aprovação
nos robôs de triagem (Gupy, Workday, Greenhouse, Taleo, Kenoby).
"""

import math
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.llm import LLMEngine
from core.models import CandidateProfile, Job

BASE_DIR = Path(__file__).resolve().parent.parent


class ATSCompatibilityScanner:
    """Simulador e Auditor de Filtros ATS para currículos."""

    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def scan(self, job: Job, custom_resume_path: Optional[str] = None) -> Dict:
        """Executa auditoria completa de ATS e retorna diagnóstico estruturado."""
        # 1. Extração do texto do CV
        resume_text = self._extract_resume_text(custom_resume_path)

        # 2. Análise de palavras-chave e hard skills
        skills_audit = self._audit_skills(job, resume_text)

        # 3. Análise de formatação e estrutura ATS
        format_audit = self._audit_formatting(resume_text)

        # 4. Análise de impacto e verbos de ação quantificados
        impact_audit = self._audit_quantified_impact(resume_text)

        # 5. Cálculo do Score Ponderado ATS (0 a 100)
        # 50% Hard Skills Match + 25% Formatação/Estrutura + 25% Métricas e Impacto
        score_skills = skills_audit["match_rate"]
        score_format = format_audit["score"]
        score_impact = impact_audit["score"]

        final_ats_score = int((score_skills * 0.50) + (score_format * 0.25) + (score_impact * 0.25))
        final_ats_score = min(100, max(10, final_ats_score))

        # 6. Recomendações acionáveis
        recommendations = self._generate_recommendations(job, skills_audit, format_audit, impact_audit)

        return {
            "overall_score": final_ats_score,
            "job_title": job.title,
            "company": job.company,
            "skills_analysis": skills_audit,
            "formatting_analysis": format_audit,
            "impact_analysis": impact_audit,
            "recommendations": recommendations,
        }

    def _extract_resume_text(self, custom_path: Optional[str] = None) -> str:
        """Extrai o texto puro do PDF do currículo usando pdfplumber ou compila do perfil."""
        pdf_path: Optional[Path] = None

        if custom_path:
            p = Path(custom_path)
            if not p.is_absolute():
                p = BASE_DIR / p
            if p.exists():
                pdf_path = p

        if not pdf_path:
            raw_path = self.profile.documents.resume_pdf_path
            p = Path(raw_path)
            if not p.is_absolute():
                p = BASE_DIR / p
            if p.exists():
                pdf_path = p

        # Tenta ler via pdfplumber
        if pdf_path and pdf_path.exists():
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pdf:
                    full_text = "\n".join([page.extract_text() or "" for page in pdf.pages])
                    if len(full_text.strip()) > 100:
                        return full_text
            except Exception:
                pass

        # Fallback: compila texto a partir dos dados do perfil estruturado
        p = self.profile
        lines = [
            p.personal_info.full_name or p.personal_info.first_name,
            p.personal_info.email,
            p.personal_info.phone,
            p.links.linkedin,
            p.links.github,
            p.professional_summary,
            "Habilidades: " + ", ".join(p.skills.primary + p.skills.secondary),
        ]
        for exp in p.experiences:
            lines.append(f"{exp.role} na {exp.company} ({exp.period}): {exp.description}")
        return "\n".join(lines)

    def _audit_skills(self, job: Job, cv_text: str) -> Dict:
        """Compara hard skills da descrição com o texto do CV."""
        job_text = f"{job.title}\n{job.description}".lower()
        cv_lower = cv_text.lower()

        # Dicionário de termos comuns de tecnologia e infraestrutura
        tech_catalog = [
            "aws", "azure", "gcp", "docker", "kubernetes", "linux", "windows",
            "python", "bash", "shell", "terraform", "cloudformation", "ansible",
            "ci/cd", "git", "github", "servicenow", "active directory", "entra id",
            "microsoft 365", "power bi", "sql", "postgresql", "mysql", "mongodb",
            "boto3", "ec2", "s3", "rds", "vpc", "iam", "cloudwatch", "lambda",
            "redes", "troubleshooting", "dns", "dhcp", "tcp/ip", "vpn", "firewall",
            "jenkins", "prometheus", "grafana", "devops", "fastapi", "flask", "node"
        ]

        # Identifica quais tecnologias a vaga pede
        demanded = []
        for tech in tech_catalog:
            pattern = r"\b" + re.escape(tech) + r"\b"
            if re.search(pattern, job_text):
                demanded.append(tech)

        if not demanded:
            # Fallback se a descrição for curta: usa as skills primárias do perfil
            demanded = [s.lower() for s in self.profile.skills.primary[:6]]

        matched = []
        missing = []

        for tech in demanded:
            pattern = r"\b" + re.escape(tech) + r"\b"
            if re.search(pattern, cv_lower):
                matched.append(tech.title())
            else:
                missing.append(tech.title())

        total = len(demanded)
        match_rate = int((len(matched) / total * 100)) if total > 0 else 70

        return {
            "demanded_skills": [d.title() for d in demanded],
            "matched_skills": matched,
            "missing_skills": missing,
            "match_rate": match_rate,
        }

    def _audit_formatting(self, cv_text: str) -> Dict:
        """Verifica a legibilidade e conformidade para parsers ATS."""
        text_lower = cv_text.lower()
        checks = {}
        score = 0

        # 1. Dados de contato essenciais presentes
        has_email = bool(re.search(r"[\w\.-]+@[\w\.-]+\.\w+", cv_text))
        has_phone = bool(re.search(r"(\+?55\s?)?\(?\d{2}\)?\s?\d{4,5}-?\d{4}", cv_text))
        has_linkedin = "linkedin.com" in text_lower
        checks["contato_completo"] = has_email and (has_phone or has_linkedin)
        if checks["contato_completo"]:
            score += 25

        # 2. Seções canônicas de ATS detectáveis
        canonical_sections = ["experiência", "formação", "competências", "habilidades", "resumo"]
        found_sections = sum(1 for sec in canonical_sections if sec in text_lower)
        checks["secoes_padronizadas"] = found_sections >= 3
        if checks["secoes_padronizadas"]:
            score += 30

        # 3. Tamanho de texto legível (não-escaneado como imagem pura)
        word_count = len(cv_text.split())
        checks["densidade_textual"] = 150 <= word_count <= 1200
        if checks["densidade_textual"]:
            score += 25

        # 4. Ausência de tabelas complexas ou fontes vazias
        checks["caracteres_legiveis"] = len(cv_text.strip()) > 300
        if checks["caracteres_legiveis"]:
            score += 20

        return {
            "score": score,
            "checks": checks,
            "word_count": word_count,
        }

    def _audit_quantified_impact(self, cv_text: str) -> Dict:
        """Verifica métricas quantificáveis (números, %, SLAs, chamados, volumetria)."""
        # Procura padrões de números seguidos de métricas (%, chamados, máquinas, dias, meses, horas)
        metrics_matches = re.findall(
            r"(\b\d+[\.,]?\d*\s?(%|máquinas|equipamentos|chamados|usuários|servidores|ms|horas|dias|minutos)\b)",
            cv_text,
            re.IGNORECASE,
        )

        count = len(metrics_matches)
        if count >= 4:
            score = 100
        elif count >= 2:
            score = 75
        elif count == 1:
            score = 50
        else:
            score = 30

        return {
            "score": score,
            "quantified_metrics_found": count,
            "sample_metrics": [m[0] for m in metrics_matches[:5]],
        }

    def _generate_recommendations(
        self, job: Job, skills_audit: Dict, format_audit: Dict, impact_audit: Dict
    ) -> List[str]:
        """Gera recomendações cirúrgicas para maximizar o score ATS antes do envio."""
        tips = []

        # Skills faltantes
        if skills_audit["missing_skills"]:
            top_missing = ", ".join(skills_audit["missing_skills"][:4])
            tips.append(
                f"Adicione menção explícita aos termos pedidos pela vaga: [bold]{top_missing}[/]. "
                "O robô ATS pode descartar o CV se essas palavras-chave não aparecerem pelo menos 1 vez no texto."
            )

        # Impacto quantificado
        if impact_audit["quantified_metrics_found"] < 3:
            tips.append(
                "Adicione métricas quantificáveis nas suas experiências (ex: 'redução de X%', 'atendimento de Y chamados/dia', 'migração de Z servidores')."
            )

        # Dados de contato
        if not format_audit["checks"].get("contato_completo"):
            tips.append("Certifique-se de que seu telefone, e-mail e link do LinkedIn estão em texto selecionável no cabeçalho.")

        if not tips:
            tips.append("Seu currículo tem excelente aderência aos requisitos e alto índice de aprovação previsto nos filtros ATS!")

        return tips
