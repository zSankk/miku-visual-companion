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


def save_api_credentials(
    api_key: str,
    model: str | None = None,
    env_file: Path | None = None,
) -> None:
    """Atualiza de forma segura e atômica o GEMINI_API_KEY e GEMINI_MODEL no arquivo .env."""
    path = env_file or (PROJECT_ROOT / ".env")
    lines: list[str] = []
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []

    clean_key = api_key.strip()
    clean_model = (model or DEFAULT_MODEL).strip()

    key_written = False
    model_written = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("GEMINI_API_KEY=") or stripped.startswith("GOOGLE_API_KEY="):
            new_lines.append(f"GEMINI_API_KEY={clean_key}")
            key_written = True
        elif stripped.startswith("GEMINI_MODEL=") or stripped.startswith("RIN_MODEL="):
            new_lines.append(f"GEMINI_MODEL={clean_model}")
            model_written = True
        else:
            new_lines.append(line)

    if not key_written:
        new_lines.append(f"GEMINI_API_KEY={clean_key}")
    if not model_written:
        new_lines.append(f"GEMINI_MODEL={clean_model}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    os.environ["GEMINI_API_KEY"] = clean_key
    os.environ["GEMINI_MODEL"] = clean_model
    os.environ["RIN_MODEL"] = clean_model


def load_settings(env_file: Path | None = None) -> Settings:
    """Carrega o `.env` (se existir) e monta o objeto `Settings`."""
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file or PROJECT_ROOT / ".env", override=True)
    except ImportError:  # python-dotenv é opcional em tempo de teste
        pass

    api_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    persona_rel = os.getenv("RIN_PERSONA_PATH", "config/persona.yaml").strip()
    persona_path = Path(persona_rel)
    if not persona_path.is_absolute():
        persona_path = PROJECT_ROOT / persona_path

    model_name = (os.getenv("GEMINI_MODEL") or os.getenv("RIN_MODEL") or DEFAULT_MODEL).strip()

    return Settings(
        api_key=api_key or None,
        model=model_name,
        temperature=_env_float("RIN_TEMPERATURE"),
        thinking_budget=_env_int("RIN_THINKING_BUDGET", 0),
        default_mode=Mode.from_str(os.getenv("RIN_DEFAULT_MODE")),
        mic_start_muted=_env_bool("RIN_MIC_START_MUTED", True),
        persona_path=persona_path,
        log_level=(os.getenv("RIN_LOG_LEVEL") or "INFO").strip().upper(),
    )
