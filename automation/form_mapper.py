"""Mapeador semântico de campos de formulário para dados do perfil."""

from typing import Dict, List, Optional
from core.models import CandidateProfile, Job
from core.llm import LLMEngine


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

        # Nome
        if any(w in text for w in ["first name", "primeiro nome", "first_name"]):
            return "first_name"
        if any(w in text for w in ["last name", "sobrenome", "last_name"]):
            return "last_name"
        if any(w in text for w in ["full name", "nome completo", "seu nome", "candidate name", "name"]):
            return "full_name"

        # Redes e Portfólio
        if "linkedin" in text:
            return "linkedin"
        if "github" in text:
            return "github"
        if any(w in text for w in ["portfolio", "website", "site", "url"]):
            return "portfolio"

        # Endereço / Cidade
        if any(w in text for w in ["city", "cidade"]):
            return "city"
        if any(w in text for w in ["state", "estado", "uf"]):
            return "state"
        if any(w in text for w in ["cep", "postal", "zip"]):
            return "postal_code"

        # Currículo / Resume (upload)
        if any(w in text for w in ["resume", "cv", "curriculo", "currículo"]):
            return "resume"

        # Salário / Pretensão
        if any(w in text for w in ["salary", "remuneração", "pretens", "salario"]):
            return "salary"

        # Carta de Apresentação / Cover Letter
        if any(w in text for w in ["cover letter", "carta de apresentação", "apresentação", "mensagem ao recrutador", "carta de motiv"]):
            return "cover_letter"

        # Demografia e Inclusão (muito comuns em ATS como Greenhouse e Gupy)
        if any(w in text for w in ["gênero", "genero", "gender"]):
            return "gender"
        if any(w in text for w in ["raça", "cor", "etnia", "race", "ethnicity"]):
            return "race_ethnicity"
        if any(w in text for w in ["deficiência", "deficiencia", "pcd", "disability"]):
            return "disability"

        # Autorização de trabalho / Visto
        if any(w in text for w in ["autorização", "trabalhar no país", "work authorization", "legally authorized", "sponsorship"]):
            return "work_authorization"

        # País / Nacionalidade
        if any(w in text for w in ["país", "pais", "country"]):
            return "country"

        # Pergunta aberta / dissertativa
        return "open_question"

    def get_value_for_field(self, field_type: str, label_text: str, job: Job) -> str:
        """Retorna o valor adequado do perfil com base no tipo semântico."""
        p = self.profile.personal_info
        links = self.profile.links

        if field_type == "first_name":
            return p.first_name or p.full_name.split()[0]
        elif field_type == "last_name":
            return p.last_name or (" ".join(p.full_name.split()[1:]) if len(p.full_name.split()) > 1 else "")
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
            return self.profile.faq_answers.get("salary_number", self.profile.faq_answers.get("salary_expectation", "8000"))
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
