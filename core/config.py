"""Gerenciamento de configurações e carregamento do perfil do candidato."""

import os
from pathlib import Path
from typing import Optional
import yaml
from dotenv import load_dotenv

from core.models import CandidateProfile

# Carrega variáveis de ambiente do .env
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def get_profile_path() -> Path:
    env_path = os.getenv("CANDIDATE_PROFILE_PATH")
    if env_path:
        p = Path(env_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        if p.exists():
            return p

    default_p = BASE_DIR / "config" / "profile.yaml"
    if default_p.exists():
        return default_p

    example_p = BASE_DIR / "config" / "profile.example.yaml"
    return example_p


def load_candidate_profile(custom_path: Optional[str] = None) -> CandidateProfile:
    """Carrega o perfil do candidato a partir do arquivo YAML."""
    if custom_path:
        path = Path(custom_path)
        if not path.is_absolute():
            path = BASE_DIR / path
    else:
        path = get_profile_path()

    if not path.exists():
        raise FileNotFoundError(f"Arquivo de perfil não encontrado em: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return CandidateProfile(**data)


def save_candidate_profile(profile: CandidateProfile, custom_path: Optional[str] = None) -> Path:
    """Salva o perfil atualizado do candidato no arquivo YAML."""
    if custom_path:
        path = Path(custom_path)
        if not path.is_absolute():
            path = BASE_DIR / path
    else:
        path = get_profile_path()
        if not path.exists() or path.name.endswith(".example.yaml"):
            path = BASE_DIR / "config" / "profile.yaml"

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile.dict(), f, allow_unicode=True, sort_keys=False)

    return path


def get_env_setting(key: str, default: str = "") -> str:
    """Retorna uma variável de ambiente ou valor padrão."""
    return os.getenv(key, default)
