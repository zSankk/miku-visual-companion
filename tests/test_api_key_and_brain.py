"""Testes unitários para o ApiKeyDialog e a resiliência do GeminiBrain."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.core.llm_client import BrainError, GeminiBrain
from src.core.settings import Settings
from src.core.state import Mode
from src.memory.session import Turn
from src.ui.api_key_dialog import AVAILABLE_GEMINI_MODELS, ApiKeyDialog


def test_gemini_brain_fallback_on_503(monkeypatch):
    """Testa se o GeminiBrain faz fallback para o próximo modelo quando o primeiro dá 503."""
    mock_client = MagicMock()
    # 1ª tentativa: 503 UNAVAILABLE
    # 2ª tentativa (retry): 503 UNAVAILABLE
    # 3ª chamada (fallback para o 2º modelo): Sucesso!
    err_503 = Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
    resp_ok = MagicMock()
    resp_ok.text = "[feliz] 5 mais 2 é 7!"

    mock_client.models.generate_content.side_effect = [err_503, err_503, resp_ok]

    with patch("google.genai.Client", return_value=mock_client), patch("time.sleep"):
        brain = GeminiBrain(
            api_key="fake-test-key",
            model="gemini-3.5-flash-lite",
            fallback_models=("gemini-flash-lite-latest",),
        )
        reply = brain.generate("Prompt sistema", [Turn("user", "quanto é 5 mais 2?")])

        assert reply == "[feliz] 5 mais 2 é 7!"
        assert brain.model == "gemini-flash-lite-latest"
        assert "gemini-flash-lite-latest" in brain.name


def test_gemini_brain_amigavel_quando_todos_falham():
    """Testa mensagem amigável quando todos os modelos retornam 503."""
    mock_client = MagicMock()
    err_503 = Exception("503 UNAVAILABLE. High demand.")
    mock_client.models.generate_content.side_effect = err_503

    with patch("google.genai.Client", return_value=mock_client), patch("time.sleep"):
        brain = GeminiBrain(
            api_key="fake-key",
            model="gemini-3.5-flash-lite",
            fallback_models=("gemini-flash-lite-latest",),
        )
        with pytest.raises(BrainError) as exc_info:
            brain.generate("Prompt", [Turn("user", "oi")])

        assert "alta demanda temporária" in str(exc_info.value)


def test_api_key_dialog_builds_and_saves(tmp_path):
    """Testa criação da janela ApiKeyDialog e salvamento da chave."""
    import customtkinter as ctk

    root = ctk.CTk()
    root.withdraw()

    saved_data = {}

    def on_saved(key, model):
        saved_data["key"] = key
        saved_data["model"] = model

    settings = Settings(
        api_key="AIzaSyOriginalKey12345",
        model="gemini-3.5-flash-lite",
        temperature=0.7,
        thinking_budget=0,
        default_mode=Mode.CASUAL,
        mic_start_muted=True,
        persona_path=tmp_path / "persona.yaml",
        log_level="INFO",
    )

    with patch("src.ui.api_key_dialog.save_api_credentials") as mock_save:
        dialog = ApiKeyDialog(root, settings=settings, on_saved=on_saved)

        # Verifica se o campo foi preenchido com a chave atual
        assert dialog.key_entry.get() == "AIzaSyOriginalKey12345"

        # Simula alteração de chave e modelo
        dialog.key_entry.delete(0, "end")
        dialog.key_entry.insert(0, "AIzaSyNovaChave67890")
        dialog.model_var.set("gemini-flash-lite-latest")

        # Salva
        dialog._save()

        mock_save.assert_called_once_with(api_key="AIzaSyNovaChave67890", model="gemini-flash-lite-latest")
        assert saved_data["key"] == "AIzaSyNovaChave67890"
        assert saved_data["model"] == "gemini-flash-lite-latest"

    root.destroy()
