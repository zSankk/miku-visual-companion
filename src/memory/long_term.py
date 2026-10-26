"""Sistema Avançado de Memória Persistente e Gerenciamento de Armazenamento da Miku.

Recursos:
- SQLite local thread-safe com caminho configurável e portabilidade via `config/settings.json`.
- Migração/cópia automática do banco ao selecionar uma nova pasta/diretório.
- Tabela `facts`: id, category (pessoal, preferencia, projeto, outros), content, confidence, is_pinned, updated_at.
- Tabela `summaries`: id, created_at, summary_text.
- Busca inteligente por relevância (Fatos fixados sempre presentes + Top 5 fatos relevantes + 3 resumos).
- Filtro estrito de privacidade por Regex (bloqueio de senhas, chaves de API, tokens, CPFs, cartões).
- Exportação e importação de backups em formato JSON (.json).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_JSON_PATH = PROJECT_ROOT / "config" / "settings.json"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "miku_memory.db"

CATEGORIES: tuple[str, ...] = ("pessoal", "preferencia", "projeto", "outros")
CONFIDENCES: tuple[str, ...] = ("confirmado", "inferencia")

_CATEGORY_ALIASES: dict[str, str] = {
    "pessoal": "pessoal",
    "pessoais": "pessoal",
    "vida": "pessoal",
    "familia": "pessoal",
    "preferencia": "preferencia",
    "preferencias": "preferencia",
    "gosto": "preferencia",
    "gostos": "preferencia",
    "projeto": "projeto",
    "projetos": "projeto",
    "trabalho": "projeto",
    "codigo": "projeto",
    "dev": "projeto",
    "outro": "outros",
    "outros": "outros",
    "geral": "outros",
}

# ----------------------------------------------------------------------------- Filtro de Dados Sensíveis
_SENSITIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),                          # Google / Gemini API key
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_\-]{16,}"),           # OpenAI / Anthropic
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),                      # GitHub tokens
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"),                   # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                              # AWS
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),     # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),                             # Hugging Face
    re.compile(
        r"\b(?:senhas?|password|passwd|pwd|passcode|api[\s_\-]?key|chave\s+(?:de\s+|da\s+)?api|"
        r"token|secret|segredo|credencia(?:l|is)|pin\s+do\s+cart[aã]o|cvv|c[oó]digo\s+de\s+seguran[cç]a)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:\d[ \-]?){13,19}\b"),                           # Cartões de crédito
    re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),                  # CPF
    re.compile(r"\b[A-Za-z0-9+/_\-]{45,}\b"),                         # Tokens longos aleatórios
)


def is_sensitive(text: str | None) -> bool:
    """Retorna True se o texto contiver senhas, chaves de API, cartões ou tokens privados."""
    if not text:
        return False
    return any(p.search(text) for p in _SENSITIVE_PATTERNS)


class SensitiveDataError(ValueError):
    """Lançado quando dados confidenciais são interceptados pela trava de privacidade."""


def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_category(raw: str | None) -> str:
    key = _strip_accents(raw or "").strip().lower()
    return _CATEGORY_ALIASES.get(key, "outros")


def normalize_confidence(raw: str | None) -> str:
    key = _strip_accents(raw or "").strip().lower()
    if key.startswith("infer"):
        return "inferencia"
    return "confirmado"


_WORD_RE = re.compile(r"[a-z0-9]{3,}")
_STOPWORDS = frozenset(
    "que com para por uma um uns umas dos das nos nas pra pro voce voces ele ela eles elas "
    "isso isto esse essa este esta aqui ali tem ter sou ser era foi mas nao sim como quando "
    "onde qual quais muito pouco mais menos meu minha seu sua the and you".split()
)


def _keywords(text: str) -> set[str]:
    words = _WORD_RE.findall(_strip_accents(text.lower()))
    return {w for w in words if w not in _STOPWORDS}


# ----------------------------------------------------------------------------- Modelos de Dados
@dataclass(frozen=True)
class Fact:
    id: int
    category: str
    content: str
    confidence: str
    is_pinned: bool
    updated_at: str
    created_at: str


@dataclass(frozen=True)
class Summary:
    id: int
    created_at: str
    summary_text: str


# ----------------------------------------------------------------------------- Configuração de Armazenamento
@dataclass
class StorageConfig:
    db_path: Path
    memory_enabled: bool = True

    @classmethod
    def load(cls, config_file: Path = SETTINGS_JSON_PATH) -> "StorageConfig":
        db_path = DEFAULT_DB_PATH
        memory_enabled = True

        if config_file.is_file():
            try:
                data = json.loads(config_file.read_text(encoding="utf-8"))
                raw_path = data.get("db_path", "").strip()
                if raw_path:
                    p = Path(raw_path)
                    db_path = p if p.is_absolute() else PROJECT_ROOT / p
                memory_enabled = bool(data.get("memory_enabled", True))
            except Exception as exc:
                log.warning("Falha ao carregar %s, usando padrão: %s", config_file, exc)

        return cls(db_path=db_path, memory_enabled=memory_enabled)

    def save(self, config_file: Path = SETTINGS_JSON_PATH) -> None:
        try:
            config_file.parent.mkdir(parents=True, exist_ok=True)
            # Salva caminho relativo se estiver sob PROJECT_ROOT para facilitar portabilidade
            try:
                rel = self.db_path.resolve().relative_to(PROJECT_ROOT.resolve())
                saved_path = str(rel).replace("\\", "/")
            except ValueError:
                saved_path = str(self.db_path)

            payload = {
                "db_path": saved_path,
                "memory_enabled": bool(self.memory_enabled),
            }
            config_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.warning("Falha ao salvar configuração em %s: %s", config_file, exc)


# ----------------------------------------------------------------------------- Esquema SQLite
_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL CHECK (category IN ('pessoal', 'preferencia', 'projeto', 'outros')),
    content     TEXT NOT NULL,
    confidence  TEXT NOT NULL DEFAULT 'confirmado' CHECK (confidence IN ('confirmado', 'inferencia')),
    is_pinned   INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS summaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    summary_text  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_category ON facts(category);
CREATE INDEX IF NOT EXISTS idx_facts_pinned ON facts(is_pinned);
"""


class MemoryStore:
    """Gerenciador central de memória persistente SQLite com recuperação inteligente."""

    def __init__(
        self,
        config: StorageConfig | None = None,
        db_path: Path | None = None,
        config_path: Path = SETTINGS_JSON_PATH,
    ) -> None:
        self.config_path = config_path
        self._lock = threading.RLock()
        self.config = config or StorageConfig.load(config_path)
        if db_path is not None:
            self.config.db_path = Path(db_path)
        self._ensure_schema()

    @property
    def db_path(self) -> Path:
        return self.config.db_path

    @property
    def enabled(self) -> bool:
        return self.config.memory_enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self.config.memory_enabled = bool(enabled)
            self.config.save(self.config_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ Troca de pasta e migração
    def change_storage_directory(self, new_dir_or_file: str | Path, migrate_existing: bool = True) -> Path:
        """Move/copia o banco SQLite atual para o novo local sem perder dados já salvos."""
        target = Path(new_dir_or_file).expanduser()
        if not target.is_absolute():
            target = PROJECT_ROOT / target

        if target.is_dir() or target.suffix.lower() != ".db":
            target.mkdir(parents=True, exist_ok=True)
            new_db_file = target / "miku_memory.db"
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            new_db_file = target

        with self._lock:
            old_db_file = self.db_path
            if (
                migrate_existing
                and old_db_file.is_file()
                and old_db_file.resolve() != new_db_file.resolve()
            ):
                if not new_db_file.exists():
                    shutil.copy2(old_db_file, new_db_file)
                    log.info("Banco de memória migrado: %s -> %s", old_db_file, new_db_file)

            self.config.db_path = new_db_file
            self.config.save(self.config_path)
            self._ensure_schema()

        return new_db_file

    # ------------------------------------------------------------------ CRUD de Fatos (facts)
    def add_fact(
        self,
        content: str,
        category: str = "outros",
        confidence: str = "confirmado",
        is_pinned: bool = False,
    ) -> Fact:
        """Adiciona ou atualiza um fato no banco. Bloqueia dados sensíveis via Regex."""
        content = " ".join((content or "").split()).strip()
        if not content:
            raise ValueError("O conteúdo da memória não pode estar vazio.")
        if is_sensitive(content):
            raise SensitiveDataError("Trava de privacidade ativada: detectado dado sensível (chave/senha/token).")

        content = content[:400]
        cat = normalize_category(category)
        conf = normalize_confidence(confidence)
        pinned = 1 if is_pinned else 0
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock, self._connect() as conn:
            # Se já existir fato igual ou equivalente, atualiza
            row = conn.execute(
                "SELECT id, is_pinned FROM facts WHERE lower(content) = lower(?)", (content,)
            ).fetchone()
            if row is not None:
                fact_id = int(row["id"])
                final_pinned = pinned if is_pinned else int(row["is_pinned"])
                conn.execute(
                    "UPDATE facts SET category = ?, confidence = ?, is_pinned = ?, updated_at = ? WHERE id = ?",
                    (cat, conf, final_pinned, now, fact_id),
                )
            else:
                cur = conn.execute(
                    "INSERT INTO facts (category, content, confidence, is_pinned, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (cat, content, conf, pinned, now, now),
                )
                fact_id = int(cur.lastrowid)

        fact = self.get_fact(fact_id)
        assert fact is not None
        return fact

    def get_fact(self, fact_id: int) -> Fact | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM facts WHERE id = ?", (int(fact_id),)).fetchone()
        return _row_to_fact(row) if row else None

    def update_fact(
        self,
        fact_id: int,
        content: str | None = None,
        category: str | None = None,
        confidence: str | None = None,
        is_pinned: bool | None = None,
    ) -> Fact | None:
        current = self.get_fact(fact_id)
        if current is None:
            return None

        new_content = " ".join((content if content is not None else current.content).split()).strip()
        if not new_content:
            raise ValueError("O conteúdo da memória não pode estar vazio.")
        if is_sensitive(new_content):
            raise SensitiveDataError("Trava de privacidade ativada: detectado dado sensível.")

        new_cat = normalize_category(category) if category is not None else current.category
        new_conf = normalize_confidence(confidence) if confidence is not None else current.confidence
        new_pinned = (1 if is_pinned else 0) if is_pinned is not None else (1 if current.is_pinned else 0)
        now = datetime.now().isoformat(timespec="seconds")

        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE facts SET content = ?, category = ?, confidence = ?, is_pinned = ?, updated_at = ? WHERE id = ?",
                (new_content[:400], new_cat, new_conf, new_pinned, now, int(fact_id)),
            )

        return self.get_fact(fact_id)

    def set_pinned(self, fact_id: int, is_pinned: bool) -> Fact | None:
        return self.update_fact(fact_id, is_pinned=is_pinned)

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM facts WHERE id = ?", (int(fact_id),))
        return cur.rowcount > 0

    def list_facts(self, category: str | None = None, search: str | None = None) -> list[Fact]:
        sql = "SELECT * FROM facts WHERE 1=1"
        params: list[Any] = []

        if category and category.lower() != "todas":
            sql += " AND category = ?"
            params.append(normalize_category(category))

        if search and search.strip():
            sql += " AND content LIKE ?"
            params.append(f"%{search.strip()}%")

        sql += " ORDER BY is_pinned DESC, updated_at DESC, id DESC"

        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [_row_to_fact(r) for r in rows]

    def clear_all(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM facts")
            conn.execute("DELETE FROM summaries")

    # ------------------------------------------------------------------ CRUD de Resumos (summaries)
    def add_summary(self, summary_text: str) -> Summary | None:
        summary_text = " ".join((summary_text or "").split()).strip()
        if not summary_text:
            return None
        if is_sensitive(summary_text):
            log.warning("Resumo descartado: contém possíveis dados sensíveis.")
            return None

        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO summaries (created_at, summary_text) VALUES (?, ?)",
                (now, summary_text[:600]),
            )
            sid = int(cur.lastrowid)

        return Summary(id=sid, created_at=now, summary_text=summary_text[:600])

    def list_summaries(self, limit: int = 10) -> list[Summary]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM summaries ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [
            Summary(id=int(r["id"]), created_at=r["created_at"], summary_text=r["summary_text"])
            for r in rows
        ]

    def delete_summary(self, summary_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM summaries WHERE id = ?", (int(summary_id),))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ Recuperação Contextual Enxuta
    def get_context_for_prompt(
        self,
        user_message: str,
        max_relevant: int = 5,
        max_summaries: int = 3,
    ) -> str:
        """Monta o bloco contextual enxuto com zero custo adicional de tokens:
        a) Todos os fatos com is_pinned = 1 (Memórias Fixadas)
        b) Top 5 fatos relevantes para user_message (sobreposição de palavras-chave + recência)
        c) Últimos 3 resumos da tabela summaries
        """
        if not self.enabled:
            return ""

        all_facts = self.list_facts()
        if not all_facts:
            summaries = self.list_summaries(limit=max_summaries)
            if not summaries:
                return ""

        # a) Todos os fatos fixados
        pinned_facts = [f for f in all_facts if f.is_pinned]
        pinned_ids = {f.id for f in pinned_facts}

        # b) Top 5 fatos relevantes não-fixados
        q_words = _keywords(user_message or "")
        non_pinned = [f for f in all_facts if f.id not in pinned_ids]

        scored: list[tuple[float, int, Fact]] = []
        for idx, f in enumerate(non_pinned):
            f_words = _keywords(f.content + " " + f.category)
            overlap = len(q_words & f_words)
            score = overlap * 4.0
            if f.confidence == "confirmado":
                score += 1.0
            score += max(0.0, 1.0 - idx * 0.05)  # bônus suave de recência
            scored.append((score, -idx, f))

        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        relevant_facts = [f for _score, _idx, f in scored[:max_relevant]]

        # c) Últimos resumos
        summaries = self.list_summaries(limit=max_summaries)

        lines: list[str] = ["[MEMÓRIA DE LONGO PRAZO - Informações sobre o usuário]"]

        if pinned_facts:
            lines.append("Fatos Essenciais (Fixados):")
            for f in pinned_facts:
                lines.append(f"- [{f.category}] {f.content}")

        if relevant_facts:
            lines.append("Fatos Relevantes:")
            for f in relevant_facts:
                tag = "" if f.confidence == "confirmado" else " (inferência)"
                lines.append(f"- [{f.category}] {f.content}{tag}")

        if summaries:
            lines.append("Resumos de Conversas Anteriores:")
            for s in summaries:
                date_str = s.created_at[:10]
                lines.append(f"- ({date_str}) {s.summary_text}")

        return "\n".join(lines)

    # ------------------------------------------------------------------ Backup (.json)
    def export_backup_json(self) -> dict[str, Any]:
        """Gera dicionário serializável com todas as memórias e resumos."""
        facts = self.list_facts()
        summaries = self.list_summaries(limit=1000)
        return {
            "version": 1,
            "exported_at": datetime.now().isoformat(),
            "facts": [
                {
                    "category": f.category,
                    "content": f.content,
                    "confidence": f.confidence,
                    "is_pinned": f.is_pinned,
                    "created_at": f.created_at,
                    "updated_at": f.updated_at,
                }
                for f in facts
            ],
            "summaries": [
                {
                    "created_at": s.created_at,
                    "summary_text": s.summary_text,
                }
                for s in summaries
            ],
        }

    def import_backup_json(self, data: dict[str, Any]) -> tuple[int, int]:
        """Importa memórias e resumos de um backup JSON. Retorna (fatos_importados, resumos_importados)."""
        if not isinstance(data, dict):
            raise ValueError("Arquivo de backup inválido.")

        imported_facts = 0
        imported_summaries = 0

        raw_facts = data.get("facts", [])
        if isinstance(raw_facts, list):
            for item in raw_facts:
                if not isinstance(item, dict):
                    continue
                content = item.get("content", "").strip()
                if not content or is_sensitive(content):
                    continue
                cat = item.get("category", "outros")
                conf = item.get("confidence", "confirmado")
                pinned = bool(item.get("is_pinned", False))
                try:
                    self.add_fact(content, cat, conf, pinned)
                    imported_facts += 1
                except Exception:
                    pass

        raw_summaries = data.get("summaries", [])
        if isinstance(raw_summaries, list):
            for item in raw_summaries:
                if not isinstance(item, dict):
                    continue
                text = item.get("summary_text", "").strip()
                if not text or is_sensitive(text):
                    continue
                try:
                    self.add_summary(text)
                    imported_summaries += 1
                except Exception:
                    pass

        return imported_facts, imported_summaries


def _row_to_fact(row: sqlite3.Row) -> Fact:
    return Fact(
        id=int(row["id"]),
        category=row["category"],
        content=row["content"],
        confidence=row["confidence"],
        is_pinned=bool(row["is_pinned"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
