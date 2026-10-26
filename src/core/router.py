"""Roteador inteligente: escolhe o caminho de cada mensagem conforme o modo.

    Modo Casual  ─► GeminiBrain (modelo rápido, custo zero/mínimo)
    Modo Dev     ─► AntigravityBridge (MCP)  ── se indisponível ──► GeminiBrain
                                                                    + prompt de Dev

Toda resposta sai pelo `emotion_parser`, então a UI sempre recebe
(emoção, texto limpo), independentemente da origem.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from src.core.emotion_parser import ParsedReply, infer_action_from_turn, parse_reply
from src.core.llm_client import Brain, GeminiBrain, OfflineBrain
from src.core.persona import Persona
from src.core.settings import Settings
from src.core.state import Mode
from src.mcp_bridge.antigravity_bridge import AntigravityBridge
from src.memory.session import SessionMemory

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouterReply:
    parsed: ParsedReply
    mode: Mode
    source: str  # quem respondeu (ex.: "Gemini (gemini-2.5-flash)", "Antigravity MCP")
    action: str | None = None

    @property
    def emotion(self) -> str:
        return self.parsed.emotion

    @property
    def text(self) -> str:
        return self.parsed.text


def create_brain(settings: Settings, persona: Persona) -> Brain:
    """Cria o cérebro adequado: Gemini se houver chave, senão Offline."""
    if not settings.has_api_key:
        log.warning("GEMINI_API_KEY não definida: usando cérebro OFFLINE (simulado).")
        return OfflineBrain()
    return GeminiBrain(
        api_key=settings.api_key or "",
        model=settings.model,
        temperature=settings.temperature if settings.temperature is not None else persona.temperature,
        max_output_tokens=persona.max_output_tokens,
        thinking_budget=settings.thinking_budget,
    )


class ConversationRouter:
    def __init__(
        self,
        persona: Persona,
        brain: Brain,
        bridge: AntigravityBridge | None = None,
        memory: SessionMemory | None = None,
        mode: Mode = Mode.CASUAL,
    ) -> None:
        self.persona = persona
        self.brain = brain
        self.bridge = bridge or AntigravityBridge()
        self.memory = memory or SessionMemory()
        self._mode = mode
        self._lock = threading.Lock()  # uma mensagem por vez

    # ------------------------------------------------------------------ modo
    @property
    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        if mode is not self._mode:
            log.info("Modo alterado: %s -> %s", self._mode.label, mode.label)
            self._mode = mode

    def toggle_mode(self) -> Mode:
        self.set_mode(Mode.DEV if self._mode is Mode.CASUAL else Mode.CASUAL)
        return self._mode

    # --------------------------------------------------------------- sessão
    def new_session(self, persona: Persona | None = None) -> None:
        self.memory.clear()
        if persona is not None:
            self.persona = persona

    # ------------------------------------------------------------- mensagens
    def handle(self, user_text: str) -> RouterReply:
        """Processa uma mensagem do usuário (BLOQUEANTE: chame fora da thread da UI)."""
        user_text = user_text.strip()
        if not user_text:
            raise ValueError("Mensagem vazia.")

        with self._lock:
            mode = self._mode
            self.memory.add_user(user_text)
            try:
                if mode is Mode.DEV and self.bridge.is_available():
                    raw, source = self._handle_dev_bridge(user_text)
                else:
                    raw = self.brain.generate(
                        self.persona.build_system_instruction(mode),
                        self.memory.context_window(),
                    )
                    source = self.brain.name
            except Exception:
                self.memory.pop_last_user()  # mantém o histórico consistente
                raise

            parsed = parse_reply(raw, default_emotion=self.persona.default_emotion)
            if not parsed.had_valid_tag:
                log.warning("Resposta sem tag de emoção válida: %r", raw[:80])
            inferred_action = infer_action_from_turn(
                user_text=user_text,
                reply_text=parsed.text,
                emotion=parsed.emotion,
                explicit_action=parsed.action,
            )
            self.memory.add_model(parsed.text, parsed.emotion, raw)
            return RouterReply(parsed=parsed, mode=mode, source=source, action=inferred_action)

    def _handle_dev_bridge(self, user_text: str) -> tuple[str, str]:  # pragma: no cover - fase MCP
        result = self.bridge.delegate(user_text)
        emotion = "feliz" if result.success else "irritada"
        return f"[{emotion}] {result.summary}", "Antigravity MCP"
