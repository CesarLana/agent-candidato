"""Consultor de Pretensão Salarial e Negociação de Ofertas.

Gera argumentos embasados e scripts de resposta para formulários e conversas
com RH, ancorando o valor nas certificações e projetos práticos do candidato.
"""

from typing import Dict, Optional
from core.models import CandidateProfile, Job


class SalaryAdvisor:
    """Consultor de pretensão e negociação salarial inteligente."""

    def __init__(self, profile: CandidateProfile):
        self.profile = profile

    def advise(self, job: Job) -> Dict:
        """Gera recomendações de pretensão e scripts de negociação para a vaga."""
        role_lower = (job.title + " " + (job.description or "")).lower()

        is_devops = any(w in role_lower for w in ["devops", "sre", "cloud"])
        is_infra = any(w in role_lower for w in ["infra", "infraestrutura", "redes", "sysadmin"])
        is_support = any(w in role_lower for w in ["suporte", "service desk", "help desk"])

        # Faixa calibrada diretamente com o perfil do candidato (R$ 2.500 a R$ 3.500 CLT)
        try:
            clt_min = float(self.profile.faq_answers.get("salary_min", 2500))
        except (ValueError, TypeError):
            clt_min = 2500.0

        try:
            clt_max = float(self.profile.faq_answers.get("salary_max", 3500))
        except (ValueError, TypeError):
            clt_max = 3500.0

        try:
            clt_target = float(self.profile.faq_answers.get("salary_number", (clt_min + clt_max) / 2))
        except (ValueError, TypeError):
            clt_target = 3000.0

        try:
            pj_target = float(self.profile.faq_answers.get("salary_pj", clt_target * 1.4))
        except (ValueError, TypeError):
            pj_target = 4500.0

        if is_devops:
            level_name = "DevOps / Cloud Jr."
        elif is_infra:
            level_name = "Analista de Infraestrutura Jr."
        elif is_support:
            level_name = "Analista de Suporte Técnico / N2"
        else:
            level_name = "Tecnologia da Informação Jr."

        s_min_str = f"{int(clt_min):_}".replace("_", ".")
        s_max_str = f"{int(clt_max):_}".replace("_", ".")
        s_tgt_str = f"{int(clt_target):_}".replace("_", ".")

        # Scripts de negociação
        form_script = f"R$ {s_tgt_str},00 CLT (aberto a propostas na faixa de R$ {s_min_str} a R$ {s_max_str} conforme benefícios)"
        
        hr_call_script = (
            f"Minha pretensão salarial está na faixa de R$ {s_min_str} a R$ {s_max_str} CLT, "
            f"mas tenho total flexibilidade dependendo do modelo de contratação e do pacote de benefícios oferecido pela {job.company}. "
            "Meu principal foco hoje é somar na infraestrutura e colocar em prática minha bagagem prática em AWS, Linux e automação."
        )

        pitch_justification = [
            "Experiência prática em ambiente bancário crítico (Itaú e B3) com processos e SLAs rigorosos.",
            "Formação AWS re/Start com projetos de IaC (CloudFormation) e conteinerização (Docker/ECR).",
            "Capacidade de automação com Python (Boto3) e Bash, reduzindo tarefas manuais repetitivas.",
            "Graduação em andamento em Análise e Desenvolvimento de Sistemas (FMU).",
        ]

        return {
            "role_category": level_name,
            "recommended_clt_range": f"R$ {clt_min:,.2f} - R$ {clt_max:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "recommended_clt_target": f"R$ {clt_target:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "recommended_pj_target": f"R$ {pj_target:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
            "form_answer": form_script,
            "interview_pitch": hr_call_script,
            "value_propositions": pitch_justification,
        }
