"""Diagnóstico rápido da Space `John6666/mikuTTS` via `gradio_client`.

Pode ser executado a qualquer momento com:
    .venv\\Scripts\\python.exe scripts/inspect_miku_tts.py
"""

from __future__ import annotations

from gradio_client import Client


def main() -> None:
    print("Conectando a John6666/mikuTTS...")
    client = Client("John6666/mikuTTS")
    client.view_api()


if __name__ == "__main__":
    main()
