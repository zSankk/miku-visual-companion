"""Ponto de entrada da Miku Virtual Companion.

Execução (na raiz do projeto, com a .venv ativa):
    python -m src.main
ou
    python src/main.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Permite `python src/main.py` além de `python -m src.main`
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.core.persona import PersonaError, load_persona  # noqa: E402
from src.core.router import ConversationRouter, create_brain  # noqa: E402
from src.core.settings import load_settings  # noqa: E402
from src.mcp_bridge.antigravity_bridge import AntigravityBridge  # noqa: E402
from src.memory.session import SessionMemory  # noqa: E402
from src.voice.mic_controller import MicController  # noqa: E402


def _fatal(message: str) -> None:
    logging.getLogger("rin").error(message)
    try:
        import tkinter.messagebox as mb

        mb.showerror("Miku Virtual Companion", message)
    except Exception:
        pass
    sys.exit(1)


def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    log = logging.getLogger("rin")

    try:
        persona = load_persona(settings.persona_path)
    except PersonaError as exc:
        _fatal(f"Não foi possível carregar a persona:\n{exc}")
        return

    try:
        brain = create_brain(settings, persona)
    except Exception as exc:
        _fatal(f"Não foi possível inicializar o cérebro da Miku:\n{exc}")
        return

    router = ConversationRouter(
        persona=persona,
        brain=brain,
        bridge=AntigravityBridge(),
        memory=SessionMemory(),
        mode=settings.default_mode,
    )
    mic = MicController(start_muted=settings.mic_start_muted)
    log.info("Iniciando %s | cérebro=%s | modo=%s", persona.name, brain.name, router.mode.label)

    from src.ui.app import RinApp  # import tardio: testes não exigem Tk

    app = RinApp(settings=settings, router=router, mic=mic)
    app.mainloop()


if __name__ == "__main__":
    main()
