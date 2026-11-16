"""Módulo de Geração de Mensagens Estratégicas de Networking e Cold Outreach.

Gera abordagens personalizadas para Tech Recruiters e Hiring Managers:
- Nota de Conexão no LinkedIn (limite estrito de 300 caracteres)
- Mensagem Direta / InMail do LinkedIn (~120 palavras)
- Cold Email para o Líder Técnico (Tech Lead / Engineering Manager)
- Mensagem de Follow-up (após 7 dias sem resposta)
- Agradecimento Pós-Entrevista (Thank You note estratégica)
"""

import os
import re
from typing import Dict, Optional
from core.llm import LLMEngine
from core.models import CandidateProfile, Job


class NetworkingCoach:
    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def generate_all_messages(self, job: Job) -> Dict[str, str]:
        """Gera todas as 5 mensagens de contato e networking para a vaga."""
        is_english = self._is_english_job(job)

        connection_note = self._generate_connection_note(job, is_english)
        inmail = self._generate_inmail(job, is_english)
        cold_email = self._generate_cold_email(job, is_english)
        follow_up = self._generate_follow_up(job, is_english)
        thank_you = self._generate_thank_you(job, is_english)

        return {
            "linkedin_connection_note": connection_note,
            "linkedin_inmail": inmail,
            "cold_email_hiring_manager": cold_email,
            "follow_up_7days": follow_up,
            "thank_you_interview": thank_you,
            "is_english": is_english,
        }

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

    def _generate_connection_note(self, job: Job, is_english: bool) -> str:
        """Gera nota de conexão do LinkedIn (<= 300 caracteres garantidos)."""
        prompt = f"""
Crie uma mensagem curta para o convite de conexão do LinkedIn com um Tech Recruiter ou Hiring Manager da empresa {job.company}.
Cargo pretendido: {job.title}
Candidato: {self.profile.personal_info.full_name or self.profile.personal_info.first_name}
Principais habilidades: {', '.join(self.profile.skills.primary[:3])}

REQUISITOS CRÍTICOS:
- MÁXIMO ABSOLUTO de 280 caracteres (o LinkedIn bloqueia acima de 300).
- Tom amigável, direto e profissional.
- Idioma: {'Inglês' if is_english else 'Português do Brasil'}.
- Não inclua saudações longas nem rodeios.
"""
        ans = self.llm._generate_raw(prompt)
        if ans and len(ans.strip()) <= 300:
            return ans.strip()

        # Fallback determinístico garantido < 300 caracteres
        first_name = self.profile.personal_info.first_name or "Olá"
        top_skills = "/".join(self.profile.skills.primary[:2]) or "Desenvolvimento"
        
        if is_english:
            note = f"Hi! I saw the {job.title} opening at {job.company}. With a strong background in {top_skills}, I'd love to connect and follow {job.company}'s engineering journey!"
        else:
            note = f"Olá! Vi a oportunidade de {job.title} na {job.company}. Atuo com foco em {top_skills} e gostaria de me conectar para acompanhar os desafios do time!"
        
        return note[:295]

    def _generate_inmail(self, job: Job, is_english: bool) -> str:
        """Gera mensagem direta / InMail detalhada para o LinkedIn."""
        prompt = f"""
Escreva uma mensagem direta de LinkedIn (InMail) convincente e de alto impacto para enviar ao Tech Recruiter ou Gerente de Engenharia da {job.company} sobre a vaga de {job.title}.

Candidato:
Nome: {self.profile.personal_info.full_name or self.profile.personal_info.first_name}
Resumo: {self.profile.professional_summary}
Skills alinhadas: {', '.join(job.skills_matched or self.profile.skills.primary[:4])}
Link LinkedIn: {self.profile.links.linkedin}

Diretrizes:
- Aproximadamente 120 a 160 palavras.
- Mostre entusiasmo autêntico pela {job.company}.
- Conecte 2 competências sólidas com o que a empresa precisa.
- Chamada para ação de baixo atrito (ex: trocar uma ideia de 10 minutos).
- Idioma: {'Inglês' if is_english else 'Português do Brasil'}.
"""
        ans = self.llm._generate_raw(prompt)
        if ans:
            return ans.strip()

        # Fallback determinístico
        name = self.profile.personal_info.full_name or self.profile.personal_info.first_name
        skills_str = ", ".join(job.skills_matched or self.profile.skills.primary[:3])

        if is_english:
            return (
                f"Hi team,\n\n"
                f"I hope you are having a productive week! I recently came across the {job.title} role at {job.company} "
                f"and was immediately drawn to the technical challenges you are tackling.\n\n"
                f"With extensive hands-on experience in {skills_str}, I have built resilient systems and helped teams deliver impactful products. "
                f"I've officially submitted my application, but wanted to reach out directly to express my genuine enthusiasm.\n\n"
                f"Would you be open to a brief 10-minute chat sometime next week to discuss how my background aligns with your engineering goals?\n\n"
                f"Best regards,\n{name}\n{self.profile.links.linkedin}"
            )
        else:
            return (
                f"Olá,\n\n"
                f"Espero que esteja tendo uma ótima semana! Acompanhei a abertura da oportunidade de {job.title} na {job.company} "
                f"e me identifiquei muito com a proposta e o desafio técnico da posição.\n\n"
                f"Tenho sólida bagagem prática desenvolvendo com {skills_str}, atuando na construção de arquiteturas escaláveis e entregas de alto impacto. "
                f"Já realizei minha candidatura oficial, mas fiz questão de fazer este contato direto pelo grande interesse na cultura e nos projetos de vocês.\n\n"
                f"Teria disponibilidade para um bate-papo rápido de 10 minutos na próxima semana?\n\n"
                f"Um abraço,\n{name}\n{self.profile.links.linkedin}"
            )

    def _generate_cold_email(self, job: Job, is_english: bool) -> str:
        """Gera Cold Email estruturado com linha de assunto atraente."""
        prompt = f"""
Escreva um Cold Email de alta conversão para o Hiring Manager / Tech Lead da empresa {job.company} referente à vaga de {job.title}.

Candidato:
Nome: {self.profile.personal_info.full_name or self.profile.personal_info.first_name}
Skills: {', '.join(self.profile.skills.primary)}
GitHub: {self.profile.links.github} | LinkedIn: {self.profile.links.linkedin}

Diretrizes:
- Inclua Linha de Assunto (Subject) direta e atraente.
- Corpo com 3 parágrafos curtos: 
  1) Gancho de abertura sobre a empresa e a vaga;
  2) O que o candidato entrega de valor prático imediato com links técnicos;
  3) Chamada para ação simples e educada.
- Idioma: {'Inglês' if is_english else 'Português do Brasil'}.
"""
        ans = self.llm._generate_raw(prompt)
        if ans:
            return ans.strip()

        name = self.profile.personal_info.full_name or self.profile.personal_info.first_name
        skills = ", ".join(self.profile.skills.primary[:3])

        if is_english:
            return (
                f"Subject: {job.title} @ {job.company} - {name} ({skills})\n\n"
                f"Hi Hiring Team,\n\n"
                f"I've been following {job.company}'s work and was thrilled to see your opening for {job.title}.\n\n"
                f"I specialize in {skills}, focusing on clean architecture, performance optimization, and reliable product delivery. "
                f"You can explore some of my open-source code and architectural patterns here: {self.profile.links.github or self.profile.links.linkedin}\n\n"
                f"I would welcome the opportunity to connect for 10 minutes to learn more about your immediate roadmap and share how I could contribute from day one.\n\n"
                f"Best regards,\n{name}\n{self.profile.personal_info.email} | {self.profile.personal_info.phone}\n{self.profile.links.linkedin}"
            )
        else:
            return (
                f"Assunto: {job.title} na {job.company} - {name} ({skills})\n\n"
                f"Prezada liderança técnica da {job.company},\n\n"
                f"Acompanho o crescimento da {job.company} e fiquei muito entusiasmado ao ver a posição de {job.title}.\n\n"
                f"Minha trajetória é focada no desenvolvimento com {skills}, atuando desde a concepção de soluções escaláveis até a otimização de performance e boas práticas de engenharia. "
                f"Fique à vontade para conferir alguns projetos e códigos no meu GitHub/LinkedIn: {self.profile.links.github or self.profile.links.linkedin}\n\n"
                f"Gostaria muito de trocar uma ideia rápida de 10 minutos sobre os desafios do time e como posso somar de imediato nas metas deste trimestre.\n\n"
                f"Atenciosamente,\n{name}\n{self.profile.personal_info.email} | {self.profile.personal_info.phone}\n{self.profile.links.linkedin}"
            )

    def _generate_follow_up(self, job: Job, is_english: bool) -> str:
        """Gera mensagem de follow-up após 7 dias de candidatura ou contato sem resposta."""
        name = self.profile.personal_info.full_name or self.profile.personal_info.first_name

        if is_english:
            return (
                f"Subject: Following up on {job.title} application - {name}\n\n"
                f"Hi team,\n\n"
                f"I hope you're having a great week! I'm following up on my application for the {job.title} position submitted last week.\n\n"
                f"I remain very excited about {job.company}'s mission and confident that my background aligns well with the team's needs. "
                f"Please let me know if there are any additional materials or details I can provide to support your review.\n\n"
                f"Thanks for your time and consideration,\n{name}"
            )
        else:
            return (
                f"Assunto: Acompanhamento da candidatura - {job.title} - {name}\n\n"
                f"Olá,\n\n"
                f"Espero que esteja tudo bem por aí! Estou passando apenas para acompanhar minha candidatura para a vaga de {job.title}, enviada na semana passada.\n\n"
                f"Continuo muito entusiasmado com a oportunidade na {job.company} e convicto de que posso agregar valor expressivo ao time. "
                f"Caso precisem de qualquer informação complementar ou link de portfólio, estou à inteira disposição.\n\n"
                f"Agradeço pela atenção,\n{name}"
            )

    def _generate_thank_you(self, job: Job, is_english: bool) -> str:
        """Gera email/mensagem de agradecimento pós-entrevista."""
        name = self.profile.personal_info.full_name or self.profile.personal_info.first_name

        if is_english:
            return (
                f"Subject: Thank you for the interview - {job.title} - {name}\n\n"
                f"Hi [Interviewer Name],\n\n"
                f"Thank you very much for taking the time to speak with me today about the {job.title} position at {job.company}. "
                f"I really enjoyed our conversation, especially learning more about your tech stack and current team priorities.\n\n"
                f"Our discussion further reinforced my desire to join {job.company} and contribute to solving these exciting challenges. "
                f"Looking forward to the next steps, and please don't hesitate to reach out if you need anything else from my side!\n\n"
                f"Best regards,\n{name}"
            )
        else:
            return (
                f"Assunto: Agradecimento pela entrevista - {job.title} - {name}\n\n"
                f"Olá [Nome do Entrevistador],\n\n"
                f"Muito obrigado pelo tempo dedicado na nossa conversa de hoje sobre a posição de {job.title} na {job.company}. "
                f"Foi ótimo conhecer mais a fundo os desafios técnicos e os projetos em andamento da equipe.\n\n"
                f"Nosso papo reforçou ainda mais minha vontade de fazer parte do time e somar aos resultados de vocês. "
                f"Fico à disposição para os próximos passos do processo seletivo!\n\n"
                f"Um abraço,\n{name}"
            )
