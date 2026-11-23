"""Módulo de Segurança Anti-Ban, Rate Limiting e Comportamento Humano.

Inspirado nas melhores práticas de repositórios como AIHawk e Applied:
1. Limites diários de candidaturas (evita spam e shadowban)
2. Janela de horário humano (aplica em horário comercial)
3. Delays aleatórios com jitter (simula tempo humano de leitura e digitação)
4. Cooldown obrigatório entre envios consecutivos
5. Histórico e persistência de envios diários no SQLite
"""

import json
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from rich.console import Console

from core.database import get_connection

console = Console(force_terminal=True, legacy_windows=False)
BASE_DIR = Path(__file__).resolve().parent.parent

# Configurações padrão de segurança
DEFAULT_DAILY_LIMIT_PER_PLATFORM = 15  # Máximo por plataforma (ex: LinkedIn)
DEFAULT_DAILY_LIMIT_TOTAL = 30         # Máximo total por dia
DEFAULT_MIN_COOLDOWN_SEC = 90          # Mínimo 1.5 min entre uma candidatura e outra
WORK_HOUR_START = 8                    # 08:00
WORK_HOUR_END = 20                     # 20:00


def _init_safety_table():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS safety_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                job_id INTEGER,
                applied_at TEXT NOT NULL
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_safety_date ON safety_logs(applied_at);")
        conn.commit()


class SafetyGuard:
    """Guarda de proteção contra banimentos e excesso de requisições."""

    def __init__(self):
        _init_safety_table()
        self.limit_per_platform = int(os.getenv("MAX_APPLICATIONS_PER_DAY_PLATFORM", DEFAULT_DAILY_LIMIT_PER_PLATFORM))
        self.limit_total = int(os.getenv("MAX_APPLICATIONS_PER_DAY_TOTAL", DEFAULT_DAILY_LIMIT_TOTAL))

    def get_applications_today(self, platform: Optional[str] = None) -> int:
        """Retorna o número de candidaturas já realizadas hoje."""
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        with get_connection() as conn:
            cursor = conn.cursor()
            if platform:
                cursor.execute(
                    "SELECT COUNT(*) FROM safety_logs WHERE applied_at LIKE ? AND platform = ?;",
                    (f"{today_prefix}%", platform.lower()),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM safety_logs WHERE applied_at LIKE ?;",
                    (f"{today_prefix}%",),
                )
            return cursor.fetchone()[0]

    def can_apply_now(self, platform: str = "generic", ignore_hours: bool = False) -> Tuple[bool, str]:
        """Valida se uma candidatura pode ser feita com segurança neste momento.

        Verifica:
        1. Limite diário por plataforma
        2. Limite diário global
        3. Horário seguro (08h às 20h para simular humano acordado)
        """
        now = datetime.now()

        # 1. Verificação de horário seguro
        if not ignore_hours:
            current_hour = now.hour
            if current_hour < WORK_HOUR_START or current_hour >= WORK_HOUR_END:
                return (
                    False,
                    f"Horário fora da janela humana ({WORK_HOUR_START:02d}:00 às {WORK_HOUR_END:02d}:00). "
                    f"Aplicar às {now.strftime('%H:%M')} aumenta risco de detecção como bot. Use --ignore-hours para forçar.",
                )

        # 2. Verificação de limite global
        total_today = self.get_applications_today()
        if total_today >= self.limit_total:
            return (
                False,
                f"Limite total diário atingido ({total_today}/{self.limit_total}). "
                "Para proteger sua conta, novas candidaturas foram pausadas até amanhã.",
            )

        # 3. Verificação de limite da plataforma
        plat_today = self.get_applications_today(platform)
        if plat_today >= self.limit_per_platform:
            return (
                False,
                f"Limite diário da plataforma '{platform.upper()}' atingido ({plat_today}/{self.limit_per_platform}). "
                "Pausado para evitar restrição ou shadowban no perfil.",
            )

        return (True, "OK")

    def record_application(self, platform: str, job_id: Optional[int] = None):
        """Registra a conclusão de uma candidatura para cálculo dos limites."""
        _init_safety_table()
        now_iso = datetime.now().isoformat()
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO safety_logs (platform, job_id, applied_at) VALUES (?, ?, ?);",
                (platform.lower(), job_id, now_iso),
            )
            conn.commit()

    def get_status_report(self) -> Dict:
        """Retorna resumo completo do uso diário e margem de segurança."""
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        total_today = self.get_applications_today()

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT platform, COUNT(*) as c FROM safety_logs WHERE applied_at LIKE ? GROUP BY platform;",
                (f"{today_prefix}%",),
            )
            by_platform = {row["platform"]: row["c"] for row in cursor.fetchall()}

        return {
            "date": today_prefix,
            "total_today": total_today,
            "limit_total": self.limit_total,
            "remaining_total": max(0, self.limit_total - total_today),
            "limit_per_platform": self.limit_per_platform,
            "by_platform": by_platform,
            "is_work_hours": (WORK_HOUR_START <= datetime.now().hour < WORK_HOUR_END),
        }

    @staticmethod
    def human_delay(min_sec: float = 1.0, max_sec: float = 3.5, label: Optional[str] = None):
        """Pausa com tempo variável aleatório para simular leitura/pensamento humano."""
        sleep_time = random.uniform(min_sec, max_sec)
        if label:
            console.print(f"[dim]⏳ {label} (pausa humana: {sleep_time:.1f}s)...[/dim]")
        time.sleep(sleep_time)

    @staticmethod
    def human_type(page_or_element, selector_or_text: str, text_to_type: Optional[str] = None):
        """Digita texto com velocidade flutuante (jitter) simulando dedos humanos."""
        if text_to_type is None:
            # Caso o elemento já seja passado diretamente
            pass
