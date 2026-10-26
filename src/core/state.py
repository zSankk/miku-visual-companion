"""Estados e modos de operação da Rin (compartilhados entre core e UI)."""

from __future__ import annotations

from enum import Enum


class AgentState(str, Enum):
    """Estado de atividade exibido no painel de Status."""

    INATIVA = "Inativa"
    OUVINDO = "Ouvindo"
    PENSANDO = "Pensando"
    FALANDO = "Falando"


class Mode(str, Enum):
    """Modo de operação do roteador.

    - CASUAL: conversa direta com o modelo rápido (custo zero/mínimo).
    - DEV: Modo Dev Antigravity, preparado para delegar ao Antigravity via MCP.
    """

    CASUAL = "casual"
    DEV = "dev"

    @classmethod
    def from_str(cls, value: str | None, default: "Mode | None" = None) -> "Mode":
        default = default or cls.CASUAL
        if not value:
            return default
        value = value.strip().lower()
        aliases = {"dev antigravity": "dev", "antigravity": "dev", "conversa": "casual"}
        value = aliases.get(value, value)
        try:
            return cls(value)
        except ValueError:
            return default

    @property
    def label(self) -> str:
        return "Casual" if self is Mode.CASUAL else "Dev Antigravity"
