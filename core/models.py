"""Modelos de dados (Pydantic) para o Agente Candidato."""

from datetime import datetime
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class PersonalInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    state: str = ""
    country: str = "Brasil"
    postal_code: str = ""
    address: str = ""


class Links(BaseModel):
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    other: str = ""


class Documents(BaseModel):
    resume_pdf_path: str = "data/curriculo.pdf"


class Skills(BaseModel):
    primary: List[str] = Field(default_factory=list)
    secondary: List[str] = Field(default_factory=list)


class Preferences(BaseModel):
    target_roles: List[str] = Field(default_factory=list)
    work_modalities: List[str] = Field(default_factory=lambda: ["Remoto", "Híbrido"])
    min_fit_score: int = 65


class ExperienceItem(BaseModel):
    company: str
    role: str
    period: str
    description: str


class STARStory(BaseModel):
    title: str = ""
    situation: str = ""
    task: str = ""
    action: str = ""
    result: str = ""
    skills: List[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    personal_info: PersonalInfo = Field(default_factory=PersonalInfo)
    links: Links = Field(default_factory=Links)
    documents: Documents = Field(default_factory=Documents)
    professional_summary: str = ""
    skills: Skills = Field(default_factory=Skills)
    preferences: Preferences = Field(default_factory=Preferences)
    faq_answers: Dict[str, str] = Field(default_factory=dict)
    experiences: List[ExperienceItem] = Field(default_factory=list)
    star_stories: List[STARStory] = Field(default_factory=list)


class Job(BaseModel):
    id: Optional[int] = None
    title: str
    company: str
    url: str
    platform: str = "generic"
    location: Optional[str] = "Não especificado"
    workplace_type: Optional[str] = "Não especificado" # Remoto, Híbrido, Presencial
    description: str = ""
    fit_score: Optional[int] = None
    fit_summary: Optional[str] = None
    skills_matched: List[str] = Field(default_factory=list)
    skills_missing: List[str] = Field(default_factory=list)
    cover_letter: Optional[str] = None
    status: str = "pending" # pending, reviewed, applied, skipped, failed
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    applied_at: Optional[str] = None
    notes: Optional[str] = None
