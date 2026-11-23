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

        # Determina faixa média de mercado (SP / Brasil) para o nível do candidato
        is_devops = any(w in role_lower for w in ["devops", "sre", "cloud"])
        is_infra = any(w in role_lower for w in ["infra", "infraestrutura", "redes", "sysadmin"])
        is_support = any(w in role_lower for w in ["suporte", "service desk", "help desk"])

        if is_devops:
            clt_min, clt_target, clt_max = 4500, 5500, 6500
            pj_target = 8000
            level_name = "DevOps / Cloud Jr."
        elif is_infra:
            clt_min, clt_target, clt_max = 3800, 4600, 5500
            pj_target = 6800
            level_name = "Analista de Infraestrutura Jr."
        elif is_support:
            clt_min, clt_target, clt_max = 2800, 3500, 4200
            pj_target = 5000
            level_name = "Analista de Suporte Técnico / N2"
        else:
            clt_min, clt_target, clt_max = 3500, 4500, 5500
            pj_target = 6500
            level_name = "Tecnologia da Informação Jr."

        # Scripts de negociação
        form_script = f"R$ {clt_target:,.2f} CLT (aberto a propostas de acordo com o pacote de benefícios)".replace(",", "X").replace(".", ",").replace("X", ".")
        
        hr_call_script = (
            f"Hoje minha pretensão está na faixa de R$ {clt_min:,.0f} a R$ {clt_max:,.0f} CLT, "
            f"mas tenho total flexibilidade dependendo do modelo de contratação e do pacote de benefícios oferecido pela {job.company}. "
            "Meu principal foco hoje é somar na infraestrutura e colocar em prática minha bagagem em AWS e automação."
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
