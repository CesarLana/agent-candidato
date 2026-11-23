"""Módulo de Inteligência Artificial para análise de Fit e respostas personalizadas."""

import json
import os
import re
from typing import List, Optional, Tuple
import requests

from core.models import CandidateProfile, Job


class LLMEngine:
    def __init__(self):
        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.model = os.getenv("LLM_MODEL", "gemini-2.0-flash")

    def _call_gemini(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        if not self.gemini_key:
            return None
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.gemini_key}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1000},
            }
            if system_instruction:
                payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

            resp = requests.post(url, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return text.strip()
        except Exception as e:
            # Falha de rede ou API
            pass
        return None

    def _call_openai(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        if not self.openai_key:
            return None
        try:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {self.openai_key}", "Content-Type": "application/json"}
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})

            payload = {"model": "gpt-4o-mini", "messages": messages, "temperature": 0.2}
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception:
            pass
        return None

    def _generate_raw(self, prompt: str, system_instruction: str = "") -> Optional[str]:
        # Prioriza Gemini se configurado, depois OpenAI
        if self.gemini_key:
            res = self._call_gemini(prompt, system_instruction)
            if res:
                return res
        if self.openai_key:
            res = self._call_openai(prompt, system_instruction)
            if res:
                return res
        return None

    def evaluate_fit(self, job: Job, profile: CandidateProfile) -> Tuple[int, str, List[str], List[str]]:
        """Calcula o fit da vaga em relação ao perfil do candidato (0 a 100), resumo e gaps."""
        prompt = f"""
Você é um avaliador de recrutamento e carreira. Compare a vaga abaixo com o perfil do candidato.

--- VAGA ---
Título: {job.title}
Empresa: {job.company}
Local / Modalidade: {job.location} | {job.workplace_type}
Descrição:
{job.description[:3500]}

--- PERFIL DO CANDIDATO ---
Resumo: {profile.professional_summary}
Skills Primárias: {', '.join(profile.skills.primary)}
Skills Secundárias: {', '.join(profile.skills.secondary)}
Cargos Desejados: {', '.join(profile.preferences.target_roles)}
Modalidades: {', '.join(profile.preferences.work_modalities)}

Responda ESTRITAMENTE em formato JSON com o seguinte schema:
{{
  "score": <número inteiro de 0 a 100>,
  "summary": "<1 ou 2 frases resumindo os pontos fortes e eventuais gaps de forma objetiva>",
  "skills_matched": ["skill1", "skill2"],
  "skills_missing": ["skill_faltante1", "skill_faltante2"]
}}
"""
        response_text = self._generate_raw(
            prompt, system_instruction="Você é um assistente técnico em recrutamento que responde apenas em JSON válido."
        )

        if response_text:
            try:
                match = re.search(r"\{.*\}", response_text, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    raw_score = parsed.get("score", 70)
                    if isinstance(raw_score, (int, float)):
                        score = int(raw_score)
                    elif isinstance(raw_score, str):
                        m = re.search(r"\d+", raw_score)
                        score = int(m.group(0)) if m else 70
                    else:
                        score = 70
                    summary = parsed.get("summary", "Compatibilidade calculada por IA.")
                    matched = list(parsed.get("skills_matched", []))
                    missing = list(parsed.get("skills_missing", []))
                    return score, summary, matched, missing
            except Exception:
                pass

        # Fallback Heurístico inteligente (sem chaves de API necessárias)
        return self._heuristic_fit(job, profile)

    def _heuristic_fit(self, job: Job, profile: CandidateProfile) -> Tuple[int, str, List[str], List[str]]:
        """Cálculo heurístico determinístico caso o usuário não tenha API Key configurada."""
        score = 50
        matched_skills = []
        missing_skills = []
        text_lower = (job.title + " " + job.description).lower()

        # Verifica correspondência de título com cargos desejados
        for target in profile.preferences.target_roles:
            if target.lower() in text_lower:
                score += 20
                break

        # Verifica correspondência de habilidades primárias
        for skill in profile.skills.primary:
            if skill.lower() in text_lower:
                score += 5
                matched_skills.append(skill)
            else:
                missing_skills.append(skill)

        # Modalidade remota
        if "remoto" in text_lower or "remote" in text_lower:
            score += 10

        score = max(20, min(score, 98))
        if matched_skills:
            summary = f"Match heurístico: detectadas competências em comum ({', '.join(matched_skills[:4])})."
        else:
            summary = "Match heurístico básico baseado em título e perfil geral."

        return score, summary, matched_skills, missing_skills[:4]

    def generate_cover_letter(self, job: Job, profile: CandidateProfile) -> str:
        """Gera uma Carta de Apresentação (Cover Letter) altamente personalizada para a vaga."""
        prompt = f"""
Você é um redator de carreiras sênior. Redija uma Carta de Apresentação (Cover Letter) impecável, concisa e atraente.

--- DADOS DA VAGA ---
Cargo: {job.title}
Empresa: {job.company}
Descrição da vaga: {job.description[:2500]}

--- DADOS DO CANDIDATO ---
Nome: {profile.personal_info.full_name or profile.personal_info.first_name}
Email: {profile.personal_info.email} | Telefone: {profile.personal_info.phone}
LinkedIn: {profile.links.linkedin} | GitHub: {profile.links.github}
Resumo Profissional: {profile.professional_summary}
Habilidades Principais: {', '.join(profile.skills.primary)}
Experiências Relevantes:
{chr(10).join([f"- {e.role} na {e.company} ({e.period}): {e.description}" for e in profile.experiences])}

Diretrizes:
1. Tom profissional, confiante e entusiasta.
2. Destaque como a experiência técnica se alinha diretamente com o que a empresa busca.
3. Máximo de 3 ou 4 parágrafos objetivos.
4. Idioma: Português do Brasil (ou Inglês se a descrição da vaga for em inglês).
5. Inclua cabeçalho e encerramento cordial.
"""
        ans = self._generate_raw(prompt)
        if ans:
            return ans

        # Fallback de Carta de Apresentação sem IA
        return (
            f"Prezada equipe de recrutamento da {job.company},\n\n"
            f"Gostaria de apresentar minha candidatura para a posição de {job.title}. "
            f"Com sólida experiência no ecossistema de desenvolvimento de software e foco em "
            f"{', '.join(profile.skills.primary[:4])}, acredito que posso contribuir significativamente para as metas da equipe.\n\n"
            f"{profile.professional_summary}\n\n"
            f"Estou à disposição para uma entrevista e para discutir como minhas habilidades podem agregar valor à {job.company}.\n\n"
            f"Atenciosamente,\n"
            f"{profile.personal_info.full_name or profile.personal_info.first_name}\n"
            f"{profile.personal_info.email} | {profile.personal_info.phone}\n"
            f"{profile.links.linkedin}"
        )

    def generate_custom_answer(self, question: str, job: Job, profile: CandidateProfile) -> str:
        """Gera resposta para perguntas dissertativas em formulários de candidatura."""
        # Primeiro checa nas respostas FAQ pré-definidas
        q_lower = question.lower()
        if any(w in q_lower for w in ["pretensão", "salário", "salary", "compensation"]):
            return profile.faq_answers.get("salary_expectation", "A combinar")
        if any(w in q_lower for w in ["aviso", "disponibilidade", "notice", "start"]):
            return profile.faq_answers.get("notice_period", "Imediata")
        if any(w in q_lower for w in ["inglês", "english"]):
            return profile.faq_answers.get("english_level", "Avançado")
        if any(w in q_lower for w in ["autorização", "visa", "sponsorship", "visto"]):
            return profile.faq_answers.get("work_authorization", "Sim")

        # Se for pergunta aberta e tiver IA
        star_context = ""
        if profile.star_stories:
            stories_formatted = []
            for s in profile.star_stories:
                stories_formatted.append(
                    f"História: '{s.title}'\n"
                    f"- Situação: {s.situation}\n"
                    f"- Tarefa: {s.task}\n"
                    f"- Ação: {s.action}\n"
                    f"- Resultado: {s.result}\n"
                    f"- Competências: {', '.join(s.skills)}"
                )
            star_context = "\n\nCasos Reais do Candidato (Método STAR):\n" + "\n---\n".join(stories_formatted)

        prompt = f"""
O candidato está se candidatando para a vaga '{job.title}' na empresa '{job.company}'.
A pergunta do formulário de candidatura é:
"{question}"

Com base nas informações do candidato:
Resumo: {profile.professional_summary}
Experiências: {', '.join([exp.company + ' (' + exp.role + ')' for exp in profile.experiences])}
Competências: {', '.join(profile.skills.primary)}
{star_context}

Diretrizes:
- Se a pergunta pedir um exemplo real, utilize prioritariamente um dos 'Casos Reais' acima aplicando o método STAR (Situação, Tarefa, Ação e Resultado).
- Gere uma resposta profissional, direta e em primeira pessoa (em português do Brasil ou no idioma da pergunta se for inglês).
- Limite-se a 2 ou 3 parágrafos curtos e objetivos.
"""
        ans = self._generate_raw(prompt)
        if ans:
            return ans

        # Fallback genérico caso não tenha API key
        return profile.professional_summary
