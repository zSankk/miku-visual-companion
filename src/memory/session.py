"""Memória de curto prazo (histórico da sessão atual).

Fase 1: apenas em RAM, apagada ao clicar em "Nova Sessão".
Fases futuras: persistência em `data/` e memória de longo prazo.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Role = Literal["user", "model"]


@dataclass(frozen=True)
class Turn:
    role: Role
    text: str  # texto visível (sem tag)
    emotion: str | None = None
    raw: str | None = None  # resposta bruta do modelo (com tag), usada como contexto
    timestamp: datetime = field(default_factory=datetime.now)


class SessionMemory:
    """Histórico thread-safe com janela máxima de turnos enviados ao modelo."""

    def __init__(self, max_turns: int = 40) -> None:
        self.max_turns = max_turns
        self._turns: list[Turn] = []
        self._lock = threading.Lock()

    def add_user(self, text: str) -> Turn:
        return self._append(Turn(role="user", text=text))

    def add_model(self, text: str, emotion: str, raw: str) -> Turn:
        return self._append(Turn(role="model", text=text, emotion=emotion, raw=raw))

    def _append(self, turn: Turn) -> Turn:
        with self._lock:
            self._turns.append(turn)
        return turn

    def pop_last_user(self) -> None:
        """Desfaz a última fala do usuário (ex.: quando a chamada à IA falha)."""
        with self._lock:
            if self._turns and self._turns[-1].role == "user":
                self._turns.pop()

    def context_window(self) -> list[Turn]:
        with self._lock:
            return list(self._turns[-self.max_turns:])

    def all(self) -> list[Turn]:
        with self._lock:
            return list(self._turns)

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._turns)
