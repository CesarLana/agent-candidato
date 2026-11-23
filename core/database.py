"""Banco de dados SQLite para persistência e rastreamento de vagas e candidaturas."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional
from core.models import Job

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "applications.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_db():
    """Cria as tabelas necessárias se não existirem e aplica migrações de colunas."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                platform TEXT DEFAULT 'generic',
                location TEXT,
                workplace_type TEXT,
                description TEXT,
                fit_score INTEGER,
                fit_summary TEXT,
                skills_matched TEXT,
                skills_missing TEXT,
                cover_letter TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                applied_at TEXT,
                notes TEXT
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_url ON jobs(url);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);")

        # Migrações seguras de colunas caso a tabela já existisse
        cursor.execute("PRAGMA table_info(jobs);")
        existing_cols = [col["name"] for col in cursor.fetchall()]

        for new_col in ["skills_matched", "skills_missing", "cover_letter"]:
            if new_col not in existing_cols:
                cursor.execute(f"ALTER TABLE jobs ADD COLUMN {new_col} TEXT;")

        conn.commit()


def _row_to_job(row: sqlite3.Row) -> Job:
    d = dict(row)
    if d.get("skills_matched") and isinstance(d["skills_matched"], str):
        try:
            d["skills_matched"] = json.loads(d["skills_matched"])
        except Exception:
            d["skills_matched"] = [s.strip() for s in d["skills_matched"].split(",") if s.strip()]
    else:
        d["skills_matched"] = []

    if d.get("skills_missing") and isinstance(d["skills_missing"], str):
        try:
            d["skills_missing"] = json.loads(d["skills_missing"])
        except Exception:
            d["skills_missing"] = [s.strip() for s in d["skills_missing"].split(",") if s.strip()]
    else:
        d["skills_missing"] = []

    return Job(**d)


def save_job(job: Job) -> Job:
    """Salva ou atualiza uma vaga no banco."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO jobs (
                title, company, url, platform, location, workplace_type,
                description, fit_score, fit_summary, skills_matched, skills_missing,
                cover_letter, status, created_at, applied_at, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                fit_score = excluded.fit_score,
                fit_summary = excluded.fit_summary,
                skills_matched = excluded.skills_matched,
                skills_missing = excluded.skills_missing,
                cover_letter = COALESCE(excluded.cover_letter, jobs.cover_letter),
                status = CASE 
                    WHEN jobs.status = 'applied' THEN 'applied' 
                    ELSE excluded.status 
                END,
                notes = COALESCE(excluded.notes, jobs.notes),
                applied_at = COALESCE(excluded.applied_at, jobs.applied_at)
            RETURNING id;
            """,
            (
                job.title,
                job.company,
                job.url,
                job.platform,
                job.location,
                job.workplace_type,
                job.description,
                job.fit_score,
                job.fit_summary,
                json.dumps(job.skills_matched, ensure_ascii=False),
                json.dumps(job.skills_missing, ensure_ascii=False),
                job.cover_letter,
                job.status,
                job.created_at,
                job.applied_at,
                job.notes,
            ),
        )
        row = cursor.fetchone()
        if row and "id" in row.keys():
            job.id = row["id"]
        elif cursor.lastrowid:
            job.id = cursor.lastrowid
        else:
            cursor.execute("SELECT id FROM jobs WHERE url = ?", (job.url,))
            found = cursor.fetchone()
            if found:
                job.id = found["id"]
        conn.commit()
    return job


def get_job_by_url(url: str) -> Optional[Job]:
    """Recupera uma vaga pela URL."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM jobs WHERE url = ?", (url,))
        row = cursor.fetchone()
        if row:
            return _row_to_job(row)
    return None


def update_job_status(
    job_id: Optional[int] = None,
    status: str = "applied",
    applied_at: Optional[str] = None,
    notes: Optional[str] = None,
    url: Optional[str] = None,
):
    """Atualiza o status de uma vaga por ID ou por URL."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if job_id is not None:
            cursor.execute(
                """
                UPDATE jobs
                SET status = ?, applied_at = COALESCE(?, applied_at), notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (status, applied_at, notes, job_id),
            )
        elif url is not None:
            cursor.execute(
                """
                UPDATE jobs
                SET status = ?, applied_at = COALESCE(?, applied_at), notes = COALESCE(?, notes)
                WHERE url = ?
                """,
                (status, applied_at, notes, url),
            )
        conn.commit()


def save_cover_letter(job_id: int, cover_letter: str):
    """Salva a carta de apresentação gerada para uma vaga."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE jobs SET cover_letter = ? WHERE id = ?", (cover_letter, job_id))
        conn.commit()


def list_jobs(status: Optional[str] = None) -> List[Job]:
    """Lista vagas cadastradas com filtro opcional por status."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY id DESC", (status,))
        else:
            cursor.execute("SELECT * FROM jobs ORDER BY id DESC")
        rows = cursor.fetchall()
        return [_row_to_job(r) for r in rows]


def export_to_csv(filepath: Optional[Path] = None) -> Path:
    """Exporta todas as candidaturas para arquivo CSV."""
    init_db()
    out_path = filepath or (BASE_DIR / "data" / "candidaturas_exportadas.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    jobs = list_jobs()
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ID",
            "Cargo",
            "Empresa",
            "Plataforma",
            "Local",
            "Modalidade",
            "Fit Score (%)",
            "Diagnóstico",
            "Status",
            "Data Criação",
            "Data Candidatura",
            "URL",
            "Notas",
        ])
        for j in jobs:
            writer.writerow([
                j.id,
                j.title,
                j.company,
                j.platform,
                j.location,
                j.workplace_type,
                j.fit_score or "",
                j.fit_summary or "",
                j.status,
                j.created_at[:10] if j.created_at else "",
                j.applied_at[:10] if j.applied_at else "",
                j.url,
                j.notes or "",
            ])

    return out_path


def get_stats() -> Dict[str, int]:
    """Retorna contadores de candidaturas por status."""
    init_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status, COUNT(*) as count FROM jobs GROUP BY status")
        rows = cursor.fetchall()
        stats = {
            "total": 0,
            "pending": 0,
            "applied": 0,
            "interview": 0,
            "offer": 0,
            "rejected": 0,
            "skipped": 0,
            "failed": 0,
        }
        for r in rows:
            st = r["status"]
            cnt = r["count"]
            stats[st] = cnt
            stats["total"] += cnt
        return stats
