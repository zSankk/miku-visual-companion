"""Testes da Fase 3: Avatar 2D Live2D (Miku Projeto Sekai), Estúdio de Modelos, Emotes e Modo Mascote."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
import zipfile

from src.avatar.live2d_widget import (
    DEFAULT_LOCAL_AVATAR_MODEL,
    AvatarSettings,
    Live2DAvatarController,
    import_live2d_model,
    scan_available_models,
)
from src.core.emotion_parser import infer_action_from_turn, parse_reply
from src.core.persona import load_persona
from src.core.router import ConversationRouter
from src.core.settings import PROJECT_ROOT
from src.core.state import AgentState


class _DummyWidget:
    def __init__(self) -> None:
        self.is_ready = True
        self.messages: list[dict[str, Any]] = []
        self.shut_down = False

    def send_message(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)

    def shutdown(self) -> None:
        self.shut_down = True


def test_persona_default_avatar_is_miku_sekai() -> None:
    persona = load_persona(PROJECT_ROOT / "config" / "persona.yaml")
    assert "miku_sekai" in persona.avatar_model_path


def test_live2d_web_assets_and_miku_sekai_model_present() -> None:
    web_dir = PROJECT_ROOT / "src" / "avatar" / "web"
    assert (web_dir / "index.html").is_file()
    assert (web_dir / "lib" / "pixi.min.js").is_file()
    assert (web_dir / "lib" / "live2d.min.js").is_file()
    assert (web_dir / "lib" / "live2dcubismcore.min.js").is_file()
    assert (web_dir / "lib" / "pixi-live2d-index.min.js").is_file()

    miku_model = PROJECT_ROOT / DEFAULT_LOCAL_AVATAR_MODEL
    assert miku_model.is_file()

    models = scan_available_models()
    assert len(models) >= 6
    folder_names = {m.folder_name for m in models}
    for expected_folder in (
        "miku_sekai_normal",
        "miku_sekai_night",
        "miku_sekai_idol",
        "miku_sekai_wonder",
        "miku_sekai",
        "haru",
    ):
        assert expected_folder in folder_names

    html = (web_dir / "index.html").read_text(encoding="utf-8")
    for token in (
        "ParamMouthOpenY",
        "PARAM_MOUTH_OPEN_Y",
        "ParamEyeLSmile",
        "PARAM_EYE_L_SMILE",
        "ParamMouthForm",
        "ParamAngleZ",
        "ParamBreath",
        "ParamShoulderL",
        "ParamArmL1",
        "ParamArmL2",
        "ParamArmR1",
        "ParamArmR2",
        "ParamArmL4",
        "ParamArmL6",
        "ParamArmR4",
        "ParamArmR6",
        "ParamHand",
        "background: transparent !important",
        "setMascotMode",
        "createAnalyser",
        "app.ticker.stop()",
        "app.ticker.start()",
    ):
        assert token in html


def test_tts_speech_clause_splitting_for_low_latency() -> None:
    from src.voice.tts import split_speech_clauses

    text = "Oi! Tudo bem com você? Hoje eu baixei vários modelos novos do Project Sekai para você testar na aba de Modelos!"
    clauses = split_speech_clauses(text)
    assert len(clauses) >= 2
    assert clauses[0] == "Oi!"
    assert len(clauses[0]) < 30


def test_action_tags_and_greeting_detection(persona) -> None:
    # Tags explícitas [acao: ...]
    p1 = parse_reply("[feliz][acao: acenar] Oi! Que bom te ver!")
    assert p1.emotion == "feliz"
    assert p1.action == "acenar"
    assert p1.text == "Oi! Que bom te ver!"

    p2 = parse_reply("[irritada] [acao: bravo] Não acredito que você fez isso!")
    assert p2.emotion == "irritada"
    assert p2.action == "bravo"
    assert "[acao" not in p2.text

    # Detecção automática de cumprimento do usuário ("oi", "olá", "bom dia", "e aí")
    for greeting in ("Oi Rin!", "Olá, tudo bem?", "E aí!", "Bom dia!"):
        assert infer_action_from_turn(greeting, "Tudo ótimo!", "feliz") == "acenar"


def test_import_live2d_zip_and_sekai_bundle(tmp_path: Path) -> None:
    models_dir = tmp_path / "models"
    zip_path = tmp_path / "21miku_custom.zip"

    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "buildmodeldata.asset",
            json.dumps(
                {
                    "Moc": "21miku_custom.moc3.bytes",
                    "Texture": ["21miku_custom.2048/texture_00.png"],
                    "Physics": "21miku_custom.physics3.json",
                }
            ),
        )
        zf.writestr("21miku_custom.moc3.bytes", b"MOC3")
        zf.writestr("21miku_custom.2048/texture_00.png", b"PNG")

    # Como o importador calcula rel_path relativo ao PROJECT_ROOT se dentro dele,
    # testamos a criação do .model3.json via _convert_sekai_buildmodeldata_if_needed
    target_test_dir = PROJECT_ROOT / "assets" / "models" / "_tmp_test_sekai"
    try:
        info = import_live2d_model(zip_path, models_dir=target_test_dir)
        assert info.abs_path.name.endswith(".model3.json")
        assert info.has_physics is True
    finally:
        import shutil

        shutil.rmtree(target_test_dir, ignore_errors=True)


def test_live2d_controller_actions_transform_lip_sync_and_gpu_saver(tmp_path: Path) -> None:
    settings = AvatarSettings(model_path=DEFAULT_LOCAL_AVATAR_MODEL)
    ctrl = Live2DAvatarController(model_path=DEFAULT_LOCAL_AVATAR_MODEL, settings=settings)
    dummy = _DummyWidget()
    ctrl.attach_widget(dummy)
    assert ctrl.is_connected()

    # Gatilhos de ação 2D
    for act in ("acenar", "feliz", "rir", "pensar", "bravo", "cantar"):
        ctrl.trigger_action(act)
        assert ctrl.last_action == act
        assert dummy.messages[-1] == {"type": "action", "value": act}

    # Sliders de Zoom, Posição X/Y e Sensibilidade LipSync
    ctrl.set_transform(zoom=1.25, offset_x=20.0, offset_y=-15.0, lip_sync_sensitivity=1.4, persist=False)
    assert ctrl.settings.zoom == 1.25
    assert ctrl.settings.offset_x == 20.0
    assert ctrl.settings.offset_y == -15.0
    assert ctrl.settings.lip_sync_sensitivity == 1.4
    assert dummy.messages[-1]["type"] == "transform"

    # Estados da conversa
    ctrl.set_state(AgentState.OUVINDO)
    assert ctrl.current_state == "listening"
    ctrl.set_state(AgentState.FALANDO)
    assert ctrl.current_state == "speaking"

    # LipSync em tempo real (escalado pela sensibilidade) e fechamento imediato (0.0)
    ctrl.set_mouth_open(0.5)
    assert ctrl.mouth_open > 0.5
    ctrl.set_mouth_open(0.0)
    assert ctrl.mouth_open == 0.0
    assert dummy.messages[-1] == {"type": "mouth", "value": 0.0}

    # Modo econômico (0% GPU)
    ctrl.set_gpu_paused(True)
    assert ctrl.gpu_paused is True
    assert dummy.messages[-1] == {"type": "pause", "value": True}

    ctrl.disconnect()
    assert dummy.shut_down is True
