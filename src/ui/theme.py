"""Paleta, fontes e metadados visuais (emoções, estados, modos).

Obs.: usamos kaomojis/símbolos do plano básico Unicode (BMP) porque o Tk no
Windows nem sempre renderiza emojis coloridos (fora do BMP) corretamente.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.state import AgentState, Mode

FONT_FAMILY = "Segoe UI"

# Paleta base (dark)
BG_APP = "#0f1115"
BG_SIDEBAR = "#151821"
BG_CARD = "#1b1f2a"
BG_CHAT = "#12151c"
BG_INPUT = "#1b1f2a"
BORDER = "#2a3040"
TEXT_PRIMARY = "#e6e8ee"
TEXT_MUTED = "#8b93a7"
ACCENT = "#e05297"  # rosa "Rin"
ACCENT_HOVER = "#c43f80"

BUBBLE_USER = "#2b3550"
BUBBLE_RIN = "#1f2433"
BUBBLE_ERROR = "#3a1d24"

MIC_ON = "#1f9d55"  # verde: microfone liberado
MIC_ON_HOVER = "#178045"
MIC_OFF = "#d93636"  # vermelho: hard mute
MIC_OFF_HOVER = "#b52a2a"


@dataclass(frozen=True)
class EmotionStyle:
    label: str
    icon: str
    color: str


EMOTION_STYLES: dict[str, EmotionStyle] = {
    "neutra": EmotionStyle("Neutra", "(・_・)", "#9aa3b5"),
    "feliz": EmotionStyle("Feliz", "(＾▽＾)", "#4ade80"),
    "irritada": EmotionStyle("Irritada", "(╬ Ò_Ó)", "#f87171"),
    "sarcasmo": EmotionStyle("Sarcasmo", "(¬‿¬)", "#c084fc"),
    "surpresa": EmotionStyle("Surpresa", "(°o°)!", "#facc15"),
    "pensativa": EmotionStyle("Pensativa", "(・・?)", "#60a5fa"),
}


def emotion_style(emotion: str | None) -> EmotionStyle:
    return EMOTION_STYLES.get(emotion or "neutra", EMOTION_STYLES["neutra"])


STATE_COLORS: dict[AgentState, str] = {
    AgentState.INATIVA: "#6b7280",
    AgentState.OUVINDO: "#22c55e",
    AgentState.PENSANDO: "#f59e0b",
    AgentState.FALANDO: "#3b82f6",
}

MODE_COLORS: dict[Mode, str] = {
    Mode.CASUAL: "#e05297",
    Mode.DEV: "#22d3ee",
}
