"""Ponte entre a Rin e o agente Antigravity via MCP.

FASE 1: STUB. A interface pública já está definida para que o roteador e a UI
não precisem mudar quando a integração real chegar.

Planejado para a fase MCP:
- Rin expõe/consome ferramentas MCP (ex.: `delegate_task`, `get_task_status`).
- Pedidos do Modo Dev são enviados ao Antigravity, e o resultado volta para a
  Rin, que o resume com sua personalidade (sempre com a tag de emoção).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class BridgeStatus(str, Enum):
    DISCONNECTED = "desconectado"
    CONNECTING = "conectando"
    CONNECTED = "conectado"


@dataclass(frozen=True)
class DevTaskResult:
    success: bool
    summary: str
    details: str = ""


class AntigravityBridge:
    """Cliente MCP para delegar tarefas de desenvolvimento ao Antigravity."""

    def __init__(self, endpoint: str | None = None) -> None:
        self.endpoint = endpoint
        self.status = BridgeStatus.DISCONNECTED

    def is_available(self) -> bool:
        """Na Fase 1 sempre `False`: o roteador usa o cérebro local como fallback."""
        return self.status is BridgeStatus.CONNECTED

    def connect(self) -> bool:
        """TODO (fase MCP): abrir sessão MCP (stdio/SSE) com o Antigravity."""
        self.status = BridgeStatus.DISCONNECTED
        return False

    def delegate(self, request: str, context: str = "") -> DevTaskResult:
        """TODO (fase MCP): enviar a tarefa e aguardar o resultado."""
        raise NotImplementedError("Ponte MCP com o Antigravity será implementada em fase futura.")

    def disconnect(self) -> None:
        self.status = BridgeStatus.DISCONNECTED
