"""Simulador e Preparador de Entrevistas Técnicas e Comportamentais com IA.

Analisa os requisitos da vaga e a trajetória do candidato para gerar um guia completo
de preparação para a entrevista (perguntas técnicas, comportamentais e perguntas estratégicas).
"""

import html
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from rich.console import Console

from core.llm import LLMEngine
from core.models import CandidateProfile, Job

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent


class InterviewCoach:
    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def generate_prep_guide(self, job: Job) -> str:
        """Gera o guia de preparação em Markdown e salva em data/."""
        star_context = ""
        if self.profile.star_stories:
            star_context = "\n".join([f"- {s.title}: {s.situation} -> {s.action} -> {s.result}" for s in self.profile.star_stories])

        prompt = f"""
Você é um Tech Recruiter sênior e líder de engenharia.
O candidato foi chamado para uma entrevista para a seguinte vaga:

Cargo: {job.title}
Empresa: {job.company}
Descrição da vaga:
{job.description[:3000]}

Perfil do Candidato:
Resumo: {self.profile.professional_summary}
Habilidades Principais: {', '.join(self.profile.skills.primary)}
Experiências: {', '.join([f'{e.role} na {e.company}' for e in self.profile.experiences])}
Casos Reais STAR do Candidato:
{star_context}

Gere um GUIA DE PREPARAÇÃO PARA ENTREVISTA completo, prático e objetivo contendo:

# 1. TOP 5 PERGUNTAS TÉCNICAS MAIS PROVÁVEIS
Para cada uma:
- A pergunta que o Tech Lead fará
- O que o entrevistador realmente quer avaliar
- Resposta recomendada destacando as tecnologias do candidato
- Armadilhas comuns a evitar

# 2. TOP 3 PERGUNTAS COMPORTAMENTAIS (MÉTODO STAR)
Para cada uma:
- A pergunta clássica de RH
- Como responder usando uma das experiências ou STAR stories do candidato

# 3. TOP 3 PERGUNTAS INTELIGENTES PARA O CANDIDATO FAZER NO FINAL
- Perguntas que demonstram senioridade técnica e visão de negócio para fazer ao Tech Lead / Gerente.

# 4. DICAS E PONTOS DE ATENÇÃO RÁPIDOS
- Cuidados específicos para a cultura da empresa ou stack da vaga.

Escreva em Markdown elegante e em Português do Brasil.
"""
        guide = self.llm._generate_raw(prompt)
        if not guide:
            guide = self._fallback_guide(job)

        # Salva o arquivo de preparação
        clean_comp = re.sub(r"[^a-zA-Z0-9_-]", "_", job.company.lower())
        clean_title = re.sub(r"[^a-zA-Z0-9_-]", "_", job.title.lower())[:25]
        out_file = BASE_DIR / "data" / f"preparacao_entrevista_{clean_comp}_{clean_title}.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)

        with open(out_file, "w", encoding="utf-8") as f:
            f.write(f"# Guia de Preparação de Entrevista: {job.title} @ {job.company}\n\n")
            f.write(f"**Data de Geração:** {job.created_at[:10]}\n\n")
            f.write(guide)

        return guide

    def _fallback_guide(self, job: Job) -> str:
        """Roteiro determinístico padrão caso não haja chave de IA configurada."""
        return f"""
## 1. Perguntas Técnicas Prováveis para {job.title}
1. **Como você estrutura a arquitetura de uma aplicação escalável?**
   - *O que esperam:* Foco em separação de camadas, APIs RESTful, microsserviços e boas práticas de banco de dados.
2. **Como você gerencia concorrência e consultas pesadas no banco?**
   - *Recomendação:* Fale sobre índices, transações, pooling de conexões e cache com Redis.
3. **Qual sua experiência com testes automatizados e CI/CD?**
   - *Recomendação:* Mencione testes unitários, de integração e pipelines Docker.

## 2. Perguntas Comportamentais (Método STAR)
1. **Conte sobre um projeto desafiador:**
   - Descreva a Situação, Tarefa, sua Ação técnica e o Resultado mensurável alcançado.
2. **Como você lida com divergências técnicas com outros devs da equipe?**
   - Destaque empatia, testes de prova de conceito (POC) e decisões baseadas em dados.

## 3. Perguntas para você fazer ao entrevistador:
- "Qual é o maior desafio técnico que o time está enfrentando neste trimestre?"
- "Como é o fluxo de deploy e a rotina de code review da equipe?"
- "Qual é o critério de sucesso para essa posição nos primeiros 90 dias?"
"""
