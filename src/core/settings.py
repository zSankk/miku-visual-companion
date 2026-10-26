"""Configurações de execução carregadas do `.env` / variáveis de ambiente."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.core.state import Mode

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = "gemini-3.5-flash-lite"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "sim", "on"}


def _env_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _env_int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    model: str
    temperature: float | None
    thinking_budget: int | None
    default_mode: Mode
    mic_start_muted: bool
    persona_path: Path
    log_level: str

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)


def load_settings(env_file: Path | None = None) -> Settings:
    """Carrega o `.env` (se existir) e monta o objeto `Settings`."""
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)
    except ImportError:  # python-dotenv é opcional em tempo de teste
        pass

    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    persona_rel = os.getenv("RIN_PERSONA_PATH", "config/persona.yaml").strip()
    persona_path = Path(persona_rel)
    if not persona_path.is_absolute():
        persona_path = PROJECT_ROOT / persona_path

    return Settings(
        api_key=api_key or None,
        model=(os.getenv("RIN_MODEL") or DEFAULT_MODEL).strip(),
        temperature=_env_float("RIN_TEMPERATURE"),
        thinking_budget=_env_int("RIN_THINKING_BUDGET", 0),
        default_mode=Mode.from_str(os.getenv("RIN_DEFAULT_MODE")),
        mic_start_muted=_env_bool("RIN_MIC_START_MUTED", True),
        persona_path=persona_path,
        log_level=(os.getenv("RIN_LOG_LEVEL") or "INFO").strip().upper(),
    )
