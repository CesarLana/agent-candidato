"""Mapeador semântico de campos de formulário para dados do perfil."""

import re
from typing import Dict, List, Optional
from core.models import CandidateProfile, Job
from core.llm import LLMEngine


def _matches_any(patterns: List[str], text: str) -> bool:
    """Verifica se algum padrão corresponde ao texto, usando limites de palavra para termos curtos (<=3 letras)."""
    for pat in patterns:
        if len(pat) <= 3:
            if re.search(r"\b" + re.escape(pat) + r"\b", text):
                return True
        else:
            if pat in text:
                return True
    return False


class FormMapper:
    def __init__(self, profile: CandidateProfile, llm_engine: Optional[LLMEngine] = None):
        self.profile = profile
        self.llm = llm_engine or LLMEngine()

    def identify_field_type(self, field_info: Dict[str, str]) -> str:
        """Identifica o significado semântico do campo analisando label, name, id e placeholder."""
        text = " ".join([
            field_info.get("label", ""),
            field_info.get("name", ""),
            field_info.get("id", ""),
            field_info.get("placeholder", ""),
            field_info.get("aria_label", ""),
        ]).lower()

        # Email
        if any(w in text for w in ["email", "e-mail"]):
            return "email"

        # Telefone
        if any(w in text for w in ["phone", "telefone", "celular", "mobile", "whatsapp"]):
            return "phone"

        # Previne que campos de empresa, escola ou usuário sejam confundidos com o nome do candidato
        if any(w in text for w in ["company", "empresa", "employer", "organization", "organização", "instituição", "school", "escola", "faculdade", "university"]):
            return "open_question"

        if any(w in text for w in ["username", "login", "usuario", "usuário"]):
            return "open_question"

        # Nome do candidato
        if any(w in text for w in ["first name", "primeiro nome", "first_name", "given name", "nome"]):
            if "last" not in text and "sobrenome" not in text and "full" not in text and "completo" not in text:
                return "first_name"
        if any(w in text for w in ["last name", "sobrenome", "last_name", "family name"]):
            return "last_name"
        if any(w in text for w in ["full name", "nome completo", "seu nome", "candidate name", "candidate_name"]):
            return "full_name"
        raw_name = field_info.get("name", "").lower().strip()
        raw_id = field_info.get("id", "").lower().strip()
        if raw_name in ["name", "nome"] or raw_id in ["name", "nome"]:
            return "full_name"

        # Redes e Portfólio
        if "linkedin" in text:
            return "linkedin"
        if "github" in text:
            return "github"
        if any(w in text for w in ["portfolio", "portfólio", "website", "personal site", "personal website"]) or (raw_name in ["site", "website", "url"]):
            return "portfolio"

        # Endereço / Cidade
        if _matches_any(["city", "cidade"], text):
            return "city"
        if _matches_any(["state", "estado", "uf"], text):
            return "state"
        if _matches_any(["cep", "postal", "zip"], text):
            return "postal_code"

        # Currículo / Resume (upload)
        if _matches_any(["resume", "cv", "curriculo", "currículo"], text):
            return "resume"

        # Salário / Pretensão
        if _matches_any(["salary", "remuneração", "pretens", "salario"], text):
            return "salary"

        # Carta de Apresentação / Cover Letter
        if _matches_any(["cover letter", "carta de apresentação", "apresentação", "mensagem ao recrutador", "carta de motiv"], text):
            return "cover_letter"

        # Demografia e Inclusão (muito comuns em ATS como Greenhouse e Gupy)
        if _matches_any(["gênero", "genero", "gender"], text):
            return "gender"
        if _matches_any(["raça", "cor", "etnia", "race", "ethnicity"], text):
            return "race_ethnicity"
        if _matches_any(["deficiência", "deficiencia", "pcd", "disability"], text):
            return "disability"

        # Autorização de trabalho / Visto
        if _matches_any(["autorização", "trabalhar no país", "work authorization", "legally authorized", "sponsorship"], text):
            return "work_authorization"

        # País / Nacionalidade
        if _matches_any(["país", "pais", "country"], text):
            return "country"

        # Pergunta aberta / dissertativa
        return "open_question"

    def get_value_for_field(self, field_type: str, label_text: str, job: Job) -> str:
        """Retorna o valor adequado do perfil com base no tipo semântico."""
        p = self.profile.personal_info
        links = self.profile.links

        name_parts = (p.full_name or "").split()
        first_from_full = name_parts[0] if name_parts else ""
        last_from_full = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        if field_type == "first_name":
            return p.first_name or first_from_full
        elif field_type == "last_name":
            return p.last_name or last_from_full
        elif field_type == "full_name":
            return p.full_name or f"{p.first_name} {p.last_name}".strip()
        elif field_type == "email":
            return p.email
        elif field_type == "phone":
            return p.phone
        elif field_type == "linkedin":
            return links.linkedin
        elif field_type == "github":
            return links.github
        elif field_type == "portfolio":
            return links.portfolio or links.other
        elif field_type == "city":
            return p.city
        elif field_type == "state":
            return p.state
        elif field_type == "country":
            return p.country or "Brasil"
        elif field_type == "postal_code":
            return p.postal_code
        elif field_type == "salary":
            return self.profile.faq_answers.get("salary_number", self.profile.faq_answers.get("salary_expectation", "3000"))
        elif field_type == "cover_letter":
            if not job.cover_letter:
                job.cover_letter = self.llm.generate_cover_letter(job, self.profile)
            return job.cover_letter
        elif field_type in ["gender", "race_ethnicity", "disability", "work_authorization"]:
            return self.profile.faq_answers.get(field_type, "Prefiro não informar")
        elif field_type == "open_question":
            return self.llm.generate_custom_answer(label_text, job, self.profile)

        return ""

    def find_best_select_option(self, available_options: List[Dict[str, str]], target_value: str) -> Optional[str]:
        """Encontra o 'value' da melhor opção em um <select> comparando texto."""
        target_lower = target_value.lower().strip()
        if not target_lower:
            return None

        for opt in available_options:
            opt_text = opt.get("text", "").lower().strip()
            opt_val = opt.get("value", "")

            # Match exato ou substring
            if target_lower == opt_text or target_lower in opt_text or opt_text in target_lower:
                return opt_val

        # Fallbacks comuns para consentimento / sim
        if target_lower in ["sim", "yes", "true"]:
            for opt in available_options:
                opt_t = opt.get("text", "").lower()
                if "sim" in opt_t or "yes" in opt_t:
                    return opt.get("value")

        # Fallbacks para "não informado" / "não"
        if "não" in target_lower or "prefiro" in target_lower:
            for opt in available_options:
                opt_t = opt.get("text", "").lower()
                if any(w in opt_t for w in ["prefiro não", "decline", "prefer not", "não", "no"]):
                    return opt.get("value")

        return None
