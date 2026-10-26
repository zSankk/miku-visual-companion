"""Integração com o VTube Studio (FASE FUTURA - stub).

Planejado:
- Conectar à API WebSocket do VTube Studio (padrão ws://localhost:8001).
- Mapear cada emoção da Rin para uma hotkey/expressão do modelo Live2D.
- Sincronizar movimento da boca com o TTS.

Na Fase 1, `set_emotion` apenas registra a última emoção recebida, para que a
UI e o roteador já possam chamá-lo sem efeitos colaterais.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Mapeamento emoção -> nome da hotkey/expressão no VTube Studio (ajustável depois).
DEFAULT_EXPRESSION_MAP: dict[str, str] = {
    "neutra": "Neutral",
    "feliz": "Happy",
    "irritada": "Angry",
    "sarcasmo": "Smug",
    "surpresa": "Surprised",
    "pensativa": "Thinking",
}


class VTubeStudioController:
    def __init__(self, url: str = "ws://localhost:8001", expression_map: dict[str, str] | None = None) -> None:
        self.url = url
        self.expression_map = expression_map or dict(DEFAULT_EXPRESSION_MAP)
        self.connected = False
        self.current_emotion: str | None = None

    def connect(self) -> bool:
        """TODO (fase VTube Studio): autenticar plugin via WebSocket."""
        return False

    def set_emotion(self, emotion: str) -> None:
        self.current_emotion = emotion
        if self.connected:  # pragma: no cover - fase futura
            raise NotImplementedError
        log.debug("[avatar stub] emoção -> %s (%s)", emotion, self.expression_map.get(emotion))

    def set_mouth_open(self, value: float) -> None:
        """TODO (fase VTube Studio): lip-sync (0.0 a 1.0)."""

    def disconnect(self) -> None:
        self.connected = False
