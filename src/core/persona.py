"""Carregamento e validação da persona (`config/persona.yaml`)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.state import Mode

REQUIRED_EMOTIONS: tuple[str, ...] = (
    "neutra",
    "feliz",
    "irritada",
    "sarcasmo",
    "surpresa",
    "pensativa",
)
REQUIRED_KEYS: tuple[str, ...] = ("name", "system_prompt", "emotions", "default_emotion")


class PersonaError(ValueError):
    """Erro de carregamento/validação do persona.yaml."""


@dataclass(frozen=True)
class Persona:
    name: str
    language: str
    system_prompt: str
    emotions: tuple[str, ...]
    default_emotion: str
    traits: tuple[str, ...] = ()
    temperature: float = 0.9
    max_output_tokens: int = 600
    mode_addenda: dict[str, str] = field(default_factory=dict)
    tts_provider: str = "miku_local"
    miku_model: str = "1a_miku_default_rvc_(aple)"
    miku_phonetic_ptbr: bool = False
    miku_timeout_s: float = 28.0
    tts_voice: str = "pt-BR-FranciscaNeural"
    tts_rate: str = "+15%"
    tts_pitch: str = "+15Hz"
    avatar_model_path: str = "assets/models/miku_sekai_normal/21miku_normal_3.0_f_t06.model3.json"

    def build_system_instruction(self, mode: Mode = Mode.CASUAL) -> str:
        """Prompt de sistema final = prompt base + complemento do modo."""
        parts = [self.system_prompt.strip()]
        addendum = self.mode_addenda.get(mode.value, "").strip()
        if addendum:
            parts.append(addendum)
        return "\n\n".join(parts)


def load_persona(path: str | Path) -> Persona:
    """Lê e valida o YAML de persona. Lança `PersonaError` se inválido."""
    path = Path(path)
    if not path.is_file():
        raise PersonaError(f"Arquivo de persona não encontrado: {path}")

    try:
        with path.open("r", encoding="utf-8") as fh:
            data: Any = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise PersonaError(f"YAML inválido em {path}: {exc}") from exc

    return persona_from_dict(data, source=str(path))


def persona_from_dict(data: Any, source: str = "<dict>") -> Persona:
    if not isinstance(data, dict):
        raise PersonaError(f"A persona em {source} deve ser um mapeamento YAML.")

    missing = [k for k in REQUIRED_KEYS if not data.get(k)]
    if missing:
        raise PersonaError(f"Campos obrigatórios ausentes em {source}: {', '.join(missing)}")

    emotions = tuple(str(e).strip().lower() for e in data["emotions"])
    absent = [e for e in REQUIRED_EMOTIONS if e not in emotions]
    if absent:
        raise PersonaError(f"Emoções obrigatórias ausentes: {', '.join(absent)}")

    default_emotion = str(data["default_emotion"]).strip().lower()
    if default_emotion not in emotions:
        raise PersonaError(f"default_emotion '{default_emotion}' não está em emotions.")

    system_prompt = str(data["system_prompt"])
    missing_tags = [e for e in emotions if f"[{e}]" not in system_prompt]
    if missing_tags:
        raise PersonaError(
            "O system_prompt deve citar todas as tags de emoção obrigatórias. "
            f"Faltando: {', '.join('[' + t + ']' for t in missing_tags)}"
        )

    generation = data.get("generation") or {}
    voice = data.get("voice") or {}
    avatar_cfg = data.get("avatar") or {}
    avatar_model_path = (
        data.get("avatar_model_path")
        or (avatar_cfg.get("avatar_model_path") if isinstance(avatar_cfg, dict) else None)
        or (avatar_cfg.get("model_path") if isinstance(avatar_cfg, dict) else None)
        or "assets/models/miku_sekai_normal/21miku_normal_3.0_f_t06.model3.json"
    )
    modes = data.get("modes") or {}
    addenda = {
        str(key): str((cfg or {}).get("prompt_addendum", ""))
        for key, cfg in modes.items()
        if isinstance(cfg, dict) or cfg is None
    }

    return Persona(
        name=str(data["name"]),
        language=str(data.get("language", "pt-BR")),
        system_prompt=system_prompt,
        emotions=emotions,
        default_emotion=default_emotion,
        traits=tuple(str(t) for t in data.get("traits", []) or []),
        temperature=float(generation.get("temperature", 0.9)),
        max_output_tokens=int(generation.get("max_output_tokens", 600)),
        mode_addenda=addenda,
        tts_provider=str(voice.get("tts_provider", "miku_local")),
        miku_model=str(voice.get("miku_model", "1a_miku_default_rvc_(aple)")),
        miku_phonetic_ptbr=bool(voice.get("miku_phonetic_ptbr", False)),
        miku_timeout_s=float(voice.get("miku_timeout_s", 28.0)),
        tts_voice=str(voice.get("tts_voice", "pt-BR-FranciscaNeural")),
        tts_rate=str(voice.get("tts_rate", "+10%")),
        tts_pitch=str(voice.get("tts_pitch", "+15Hz")),
        avatar_model_path=str(avatar_model_path).strip(),
    )
