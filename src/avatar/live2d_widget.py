"""Renderizador Live2D 2D Embutido (Projeto Sekai / Cubism 4 & 2) + Gerenciador de Modelos.

Integra um canvas HTML5 transparente via Microsoft Edge WebView2 diretamente
dentro de um `CTkFrame` do CustomTkinter (Win32 `SetParent`), zero programas
externos (sem VTube Studio) e com suporte a:
- Hatsune Miku (Projeto Sekai / Vocaloid) em `assets/models/miku_sekai/` como padrão
- Escaneamento e Importação de modelos Live2D (`.zip`, pasta, `.model3.json`, `.model.json`)
- Ajustes visuais em tempo real (Zoom/Escala, Posição X/Y e Sensibilidade do LipSync)
- Gatilhos de Ação 2D (`[acao: acenar]`, `[acao: feliz]`, `[acao: rir]`, `[acao: pensar]`, `[acao: bravo]`, `[acao: cantar]`)
- Painel Soundboard / Teste Rápido de Emotes embutido (`👋 Acenar`, `😊 Sorrir`, `🤔 Pensar`, `💢 Irritada`, `🎵 Cantar/Falar`)
- Modo Econômico (`Ocultar Avatar (Economizar GPU)`) que pausa `app.ticker.stop()` (0% GPU).
"""

from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Callable
from urllib.parse import quote
import zipfile

import customtkinter as ctk
import yaml

from src.core.settings import PROJECT_ROOT
from src.core.state import AgentState
from src.ui import theme

log = logging.getLogger(__name__)

DEFAULT_AVATAR_MODEL_URL = "assets/models/miku_sekai_normal/21miku_normal_3.0_f_t06.model3.json"
DEFAULT_LOCAL_AVATAR_MODEL = "assets/models/miku_sekai_normal/21miku_normal_3.0_f_t06.model3.json"
HARU_LOCAL_AVATAR_MODEL = "assets/models/haru/haru_greeter_t03.model3.json"

AVATAR_SETTINGS_PATH = PROJECT_ROOT / "data" / "avatar_settings.json"
MODELS_ROOT_DIR = PROJECT_ROOT / "assets" / "models"

_STATE_MAP: dict[AgentState | str, str] = {
    AgentState.INATIVA: "idle",
    AgentState.OUVINDO: "listening",
    AgentState.PENSANDO: "thinking",
    AgentState.FALANDO: "speaking",
    "inativa": "idle",
    "ouvindo": "listening",
    "pensando": "thinking",
    "falando": "speaking",
    "idle": "idle",
    "listening": "listening",
    "thinking": "thinking",
    "speaking": "speaking",
}

KNOWN_MODEL_TITLES: dict[str, tuple[str, str]] = {
    "miku_sekai_normal": (
        "Hatsune Miku · Projeto Sekai 3.0 (Original)",
        "Modelo oficial Cubism 4 do Project Sekai (3.0) com física completa de cabelo/roupa e 16 animações.",
    ),
    "miku_sekai_night": (
        "Hatsune Miku · Nightcord at 25:00 (Sekai)",
        "Miku do Empty Sekai (Nightcord) em Live2D Cubism 4 com física suave e 16 motions expressivas.",
    ),
    "miku_sekai_idol": (
        "Hatsune Miku · More More Jump! Idol (Sekai)",
        "Miku Idol de palco do Project Sekai em Cubism 4 com figurino de show e 16 animações.",
    ),
    "miku_sekai_wonder": (
        "Hatsune Miku · Wonderlands x Showtime (Sekai)",
        "Miku super energética do Wonderland Sekai em Cubism 4 com orelhinhas e 16 animações.",
    ),
    "miku_sekai": (
        "Hatsune Miku · Vocaloid Clássica",
        "Modelo clássico Vocaloid V2 com física de maria-chiquinha (Twin-Tails) e 8 motions.",
    ),
    "haru": (
        "Haru Greeter · Live2D Cubism 4",
        "Modelo oficial Live2D Cubism 4 com 8 expressões faciais e 27 animações corporais.",
    ),
}


@dataclass
class AvatarSettings:
    """Configurações persistentes de modelo, enquadramento e LipSync."""

    model_path: str = DEFAULT_LOCAL_AVATAR_MODEL
    zoom: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    lip_sync_sensitivity: float = 1.0

    def save(self, path: Path = AVATAR_SETTINGS_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.warning("Falha ao salvar avatar_settings.json: %s", exc)

    @classmethod
    def load(cls, path: Path = AVATAR_SETTINGS_PATH, fallback_model: str = "") -> AvatarSettings:
        default_model = (fallback_model or DEFAULT_LOCAL_AVATAR_MODEL).strip()
        if not path.is_file():
            return cls(model_path=default_model)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls(model_path=default_model)
            saved_model = str(raw.get("model_path") or default_model)
            if saved_model.endswith("miku_sekai/21miku_normal.model3.json"):
                saved_model = DEFAULT_LOCAL_AVATAR_MODEL
            return cls(
                model_path=saved_model,
                zoom=float(raw.get("zoom", 1.0)),
                offset_x=float(raw.get("offset_x", 0.0)),
                offset_y=float(raw.get("offset_y", 0.0)),
                lip_sync_sensitivity=float(raw.get("lip_sync_sensitivity", 1.0)),
            )
        except Exception:
            return cls(model_path=default_model)


@dataclass(frozen=True)
class AvatarModelInfo:
    """Metadados de um modelo Live2D instalado em `assets/models/`."""

    name: str
    description: str
    folder_name: str
    rel_path: str
    abs_path: Path
    sdk_label: str
    motions_count: int
    expressions_count: int
    has_physics: bool
    preview_texture: Path | None = None


def _convert_sekai_buildmodeldata_if_needed(folder: Path) -> None:
    """Se a pasta contiver um `buildmodeldata.asset` do Project Sekai sem `.model3.json`, gera o `.model3.json`."""
    existing = list(folder.rglob("*.model3.json")) + list(folder.rglob("*.model.json"))
    if existing:
        return
    for asset_file in folder.rglob("buildmodeldata.asset"):
        try:
            data = json.loads(asset_file.read_text(encoding="utf-8"))
            base_dir = asset_file.parent
            moc_rel = str(data.get("Moc") or "model.moc3").replace(".bytes", "")
            textures = [str(t) for t in (data.get("Texture") or data.get("Textures") or [])]
            physics_rel = str(data.get("Physics") or "").replace(".bytes", "")
            # Renomeia arquivos .bytes caso existam
            for bfile in base_dir.rglob("*.bytes"):
                target = bfile.with_name(bfile.name.replace(".bytes", ""))
                if not target.exists():
                    bfile.rename(target)
            model3: dict[str, Any] = {
                "Version": 3,
                "FileReferences": {
                    "Moc": moc_rel,
                    "Textures": textures,
                },
                "Groups": [
                    {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
                    {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
                ],
            }
            if physics_rel:
                model3["FileReferences"]["Physics"] = physics_rel
            out_file = base_dir / f"{base_dir.name}.model3.json"
            out_file.write_text(json.dumps(model3, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("Não foi possível converter buildmodeldata.asset em %s: %s", asset_file, exc)


def _inspect_model_json(json_path: Path) -> AvatarModelInfo:
    rel_path = json_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    folder_name = json_path.parent.name
    try:
        meta = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    is_cubism34 = json_path.name.endswith(".model3.json") or "FileReferences" in meta
    sdk_label = "Cubism 4 / Sekai (.model3.json)" if is_cubism34 else "Live2D Vocaloid (.model.json)"

    motions_count = 0
    expressions_count = 0
    has_physics = False
    preview_tex: Path | None = None

    if is_cubism34:
        refs = meta.get("FileReferences") or {}
        has_physics = bool(refs.get("Physics"))
        expressions_count = len(refs.get("Expressions") or [])
        for grp in (refs.get("Motions") or {}).values():
            if isinstance(grp, list):
                motions_count += len(grp)
        textures = refs.get("Textures") or []
        if textures and isinstance(textures[0], str):
            cand = json_path.parent / textures[0]
            if cand.is_file():
                preview_tex = cand
    else:
        has_physics = bool(meta.get("physics"))
        expressions_count = len(meta.get("expressions") or [])
        for grp in (meta.get("motions") or {}).values():
            if isinstance(grp, list):
                motions_count += len(grp)
        textures = meta.get("textures") or []
        if textures and isinstance(textures[0], str):
            cand = json_path.parent / textures[0]
            if cand.is_file():
                preview_tex = cand

    if folder_name in KNOWN_MODEL_TITLES:
        title, desc = KNOWN_MODEL_TITLES[folder_name]
    else:
        pretty = folder_name.replace("_", " ").replace("-", " ").strip().title()
        title = f"{pretty} ({json_path.stem})"
        desc = f"Modelo Live2D em assets/models/{folder_name}/"

    return AvatarModelInfo(
        name=title,
        description=desc,
        folder_name=folder_name,
        rel_path=rel_path,
        abs_path=json_path,
        sdk_label=sdk_label,
        motions_count=motions_count,
        expressions_count=expressions_count,
        has_physics=has_physics,
        preview_texture=preview_tex,
    )


def scan_available_models(models_dir: Path = MODELS_ROOT_DIR) -> list[AvatarModelInfo]:
    """Lista todos os modelos Live2D disponíveis em `assets/models/`, priorizando a Miku."""
    models_dir.mkdir(parents=True, exist_ok=True)
    _convert_sekai_buildmodeldata_if_needed(models_dir)

    found_paths: list[Path] = []
    for ext in ("*.model3.json", "*.model.json"):
        for p in models_dir.rglob(ext):
            if p not in found_paths:
                found_paths.append(p)

    infos = [_inspect_model_json(p) for p in found_paths]

    def _sort_key(info: AvatarModelInfo) -> tuple[int, str]:
        if "miku" in info.folder_name.lower() or "miku" in info.name.lower():
            return (0, info.name.lower())
        return (1, info.name.lower())

    infos.sort(key=_sort_key)
    return infos


def import_live2d_model(source: str | Path, models_dir: Path = MODELS_ROOT_DIR) -> AvatarModelInfo:
    """Importa um arquivo `.zip`, uma pasta de modelo ou um `.model3.json`/`.model.json` para `assets/models/`."""
    src_path = Path(source).expanduser().resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"Arquivo ou pasta não encontrado: {src_path}")

    models_dir.mkdir(parents=True, exist_ok=True)

    # Caso 1: Arquivo .zip
    if src_path.is_file() and src_path.suffix.lower() == ".zip":
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", src_path.stem).strip("_").lower() or "custom_model"
        target_dir = models_dir / slug
        counter = 2
        while target_dir.exists():
            target_dir = models_dir / f"{slug}_{counter}"
            counter += 1
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(src_path, "r") as zf:
            zf.extractall(target_dir)
        _convert_sekai_buildmodeldata_if_needed(target_dir)
        candidates = list(target_dir.rglob("*.model3.json")) + list(target_dir.rglob("*.model.json"))
        if not candidates:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError(
                "O arquivo .zip não contém nenhum arquivo .model3.json, .model.json ou buildmodeldata.asset."
            )
        return _inspect_model_json(candidates[0])

    # Caso 2: Usuário selecionou diretamente um .model3.json / .model.json
    if src_path.is_file() and (
        src_path.name.endswith(".model3.json") or src_path.name.endswith(".model.json")
    ):
        # Se já está dentro de assets/models/, apenas retorna
        try:
            src_path.relative_to(models_dir.resolve())
            return _inspect_model_json(src_path)
        except ValueError:
            src_folder = src_path.parent
            return import_live2d_model(src_folder, models_dir=models_dir)

    # Caso 3: Pasta contendo o modelo
    if src_path.is_dir():
        try:
            src_path.relative_to(models_dir.resolve())
            _convert_sekai_buildmodeldata_if_needed(src_path)
            candidates = list(src_path.rglob("*.model3.json")) + list(src_path.rglob("*.model.json"))
            if not candidates:
                raise ValueError("A pasta selecionada não contém um modelo Live2D (.model3.json / .model.json).")
            return _inspect_model_json(candidates[0])
        except ValueError:
            pass

        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", src_path.name).strip("_").lower() or "custom_model"
        target_dir = models_dir / slug
        counter = 2
        while target_dir.exists():
            target_dir = models_dir / f"{slug}_{counter}"
            counter += 1
        shutil.copytree(src_path, target_dir)
        _convert_sekai_buildmodeldata_if_needed(target_dir)
        candidates = list(target_dir.rglob("*.model3.json")) + list(target_dir.rglob("*.model.json"))
        if not candidates:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise ValueError("A pasta importada não contém arquivos .model3.json ou .model.json.")
        return _inspect_model_json(candidates[0])

    raise ValueError("Selecione um arquivo .zip, uma pasta ou um arquivo .model3.json / .model.json.")


def update_persona_yaml_avatar_path(model_rel_path: str, persona_path: Path | None = None) -> None:
    """Atualiza `avatar_model_path` no `config/persona.yaml` mantendo os comentários."""
    target = persona_path or (PROJECT_ROOT / "config" / "persona.yaml")
    if not target.is_file():
        return
    try:
        content = target.read_text(encoding="utf-8")
        if re.search(r"^avatar_model_path\s*:", content, flags=re.MULTILINE):
            updated = re.sub(
                r'^avatar_model_path\s*:.*$',
                f'avatar_model_path: "{model_rel_path}"',
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            updated = content.rstrip() + f'\n\navatar_model_path: "{model_rel_path}"\n'
        target.write_text(updated, encoding="utf-8")
    except Exception as exc:
        log.warning("Não foi possível atualizar avatar_model_path no persona.yaml: %s", exc)


class Live2DAvatarController:
    """Controlador de estado, expressões, emotes e parâmetros do Avatar Live2D."""

    def __init__(
        self,
        model_path: str = DEFAULT_LOCAL_AVATAR_MODEL,
        settings: AvatarSettings | None = None,
    ) -> None:
        self.settings = settings or AvatarSettings.load(fallback_model=model_path or DEFAULT_LOCAL_AVATAR_MODEL)
        if model_path and model_path != DEFAULT_LOCAL_AVATAR_MODEL:
            self.settings.model_path = model_path.strip()
        self._model_path = self.settings.model_path or DEFAULT_LOCAL_AVATAR_MODEL
        self._current_emotion = "neutra"
        self._current_state = "idle"
        self._last_action: str | None = None
        self._mouth_open = 0.0
        self._gpu_paused = False
        self._widget: Any = None
        self._last_mouth_sent_ts = 0.0
        self._last_mouth_sent_val = -1.0

    @property
    def model_path(self) -> str:
        return self._model_path

    @property
    def current_emotion(self) -> str:
        return self._current_emotion

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def last_action(self) -> str | None:
        return self._last_action

    @property
    def mouth_open(self) -> float:
        return self._mouth_open

    @property
    def gpu_paused(self) -> bool:
        return self._gpu_paused

    def attach_widget(self, widget: Any) -> None:
        """Conecta o widget visual WebView2 a este controlador."""
        self._widget = widget
        widget.send_message({"type": "model", "value": self._model_path})
        widget.send_message(
            {
                "type": "transform",
                "zoom": self.settings.zoom,
                "offsetX": self.settings.offset_x,
                "offsetY": self.settings.offset_y,
                "lipSyncSensitivity": self.settings.lip_sync_sensitivity,
            }
        )
        widget.send_message({"type": "emotion", "value": self._current_emotion})
        widget.send_message({"type": "state", "value": self._current_state})
        widget.send_message({"type": "pause", "value": self._gpu_paused})

    def is_connected(self) -> bool:
        return self._widget is not None and bool(getattr(self._widget, "is_ready", False))

    def set_model_path(self, model_path: str, persist: bool = True) -> None:
        cleaned = (model_path or DEFAULT_LOCAL_AVATAR_MODEL).strip().replace("\\", "/")
        if not cleaned:
            cleaned = DEFAULT_LOCAL_AVATAR_MODEL
        self._model_path = cleaned
        self.settings.model_path = cleaned
        if persist:
            self.settings.save()
            update_persona_yaml_avatar_path(cleaned)
        if self._widget is not None:
            self._widget.send_message({"type": "model", "value": self._model_path})

    def set_transform(
        self,
        zoom: float | None = None,
        offset_x: float | None = None,
        offset_y: float | None = None,
        lip_sync_sensitivity: float | None = None,
        persist: bool = True,
    ) -> None:
        """Atualiza Zoom (Escala), Posição X/Y e Sensibilidade do LipSync em tempo real."""
        if zoom is not None:
            self.settings.zoom = round(max(0.45, min(2.2, float(zoom))), 2)
        if offset_x is not None:
            self.settings.offset_x = round(max(-220.0, min(220.0, float(offset_x))), 1)
        if offset_y is not None:
            self.settings.offset_y = round(max(-220.0, min(220.0, float(offset_y))), 1)
        if lip_sync_sensitivity is not None:
            self.settings.lip_sync_sensitivity = round(max(0.2, min(2.5, float(lip_sync_sensitivity))), 2)

        if persist:
            self.settings.save()

        if self._widget is not None:
            self._widget.send_message(
                {
                    "type": "transform",
                    "zoom": self.settings.zoom,
                    "offsetX": self.settings.offset_x,
                    "offsetY": self.settings.offset_y,
                    "lipSyncSensitivity": self.settings.lip_sync_sensitivity,
                }
            )

    def set_emotion(self, emotion: str) -> None:
        """Aciona a expressão facial nativa + modulação universal de parâmetros Live2D."""
        self._current_emotion = (emotion or "neutra").strip().lower()
        if self._widget is not None:
            self._widget.send_message({"type": "emotion", "value": self._current_emotion})

    def trigger_action(self, action: str) -> None:
        """Dispara um gatilho de ação 2D (`acenar`, `feliz`, `rir`, `pensar`, `bravo`, `cantar`)."""
        cleaned = (action or "").strip().lower()
        if not cleaned:
            return
        self._last_action = cleaned
        if self._widget is not None:
            self._widget.send_message({"type": "action", "value": cleaned})

    def set_state(self, state: AgentState | str) -> None:
        """Altera o comportamento corporal conforme o estado da conversa."""
        mapped = _STATE_MAP.get(state, "idle")
        if isinstance(state, str) and state.lower() in _STATE_MAP:
            mapped = _STATE_MAP[state.lower()]
        self._current_state = mapped
        if mapped != "speaking":
            self._mouth_open = 0.0
        if self._widget is not None:
            self._widget.send_message({"type": "state", "value": mapped})

    def set_mouth_open(self, value: float) -> None:
        """Atualiza o parâmetro `ParamMouthOpenY` (0.0 a 1.0) a 60 FPS."""
        clamped = max(0.0, min(1.0, float(value) * self.settings.lip_sync_sensitivity))
        if clamped <= 0.01:
            clamped = 0.0
        self._mouth_open = clamped

        if self._widget is None or self._gpu_paused:
            return

        now = time.perf_counter()
        if clamped == 0.0 or abs(clamped - self._last_mouth_sent_val) >= 0.015:
            if clamped == 0.0 or (now - self._last_mouth_sent_ts) >= 0.014:
                self._last_mouth_sent_ts = now
                self._last_mouth_sent_val = clamped
                self._widget.send_message({"type": "mouth", "value": round(clamped, 3)})

    def set_gpu_paused(self, paused: bool) -> None:
        """Pausa (`app.ticker.stop()`) ou retoma (`app.ticker.start()`) o loop WebGL."""
        self._gpu_paused = bool(paused)
        if self._widget is not None:
            self._widget.send_message({"type": "pause", "value": self._gpu_paused})

    def disconnect(self) -> None:
        """Encerra o componente WebView2 limpo ao fechar a aplicação."""
        if self._widget is not None:
            try:
                self._widget.shutdown()
            except Exception:
                pass
            self._widget = None


class Live2DAvatarWidget(ctk.CTkFrame):
    """Painel visual CustomTkinter que hospeda o canvas Live2D + Soundboard de Emotes."""

    def __init__(
        self,
        master,
        controller: Live2DAvatarController,
        width: int = 340,
        on_test_sing_speak: Callable[[], None] | None = None,
        on_toggle_mascot: Callable[[], None] | None = None,
        on_mascot_drag_start: Callable[[int, int], None] | None = None,
        on_mascot_drag_move: Callable[[int, int], None] | None = None,
        on_toggle_mascot_chat: Callable[[], None] | None = None,
        on_mascot_scale: Callable[[int], None] | None = None,
        dispatch_ui: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            width=width,
            fg_color=theme.BG_CHAT,
            corner_radius=14,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.controller = controller
        self._on_test_sing_speak = on_test_sing_speak
        self._on_toggle_mascot = on_toggle_mascot
        self._on_mascot_drag_start = on_mascot_drag_start
        self._on_mascot_drag_move = on_mascot_drag_move
        self._on_toggle_mascot_chat = on_toggle_mascot_chat
        self._on_mascot_scale = on_mascot_scale
        self._dispatch_ui = dispatch_ui
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # 1. Cabeçalho compacto com botão de destaque "📌 Fixar no Canto da Tela (Modo Mascote)"
        self.top_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.top_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self.top_bar.grid_columnconfigure(0, weight=1)

        self.mascot_btn = ctk.CTkButton(
            self.top_bar,
            text="📌 Fixar no Canto da Tela (Modo Mascote)",
            height=30,
            corner_radius=8,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._handle_toggle_mascot,
        )
        self.mascot_btn.grid(row=0, column=0, sticky="ew")

        # 2. Container interno onde a janela nativa do WebView2 é embutida
        self.viewport = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CHAT,
            corner_radius=10,
        )
        self.viewport.grid(row=1, column=0, sticky="nsew", padx=4, pady=2)

        self._placeholder = ctk.CTkLabel(
            self.viewport,
            text="Inicializando Hatsune Miku Live2D...",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self._placeholder.place(relx=0.5, rely=0.5, anchor="center")

        # 3. Soundboard / Painel de Teste Rápido de Emotes
        self.emote_bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CARD,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.emote_bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))
        for col in range(5):
            self.emote_bar.grid_columnconfigure(col, weight=1)

        emote_buttons = [
            ("👋 Acenar", lambda: self.controller.trigger_action("acenar")),
            ("😊 Sorrir", lambda: self.controller.trigger_action("feliz")),
            ("🤔 Pensar", lambda: self.controller.trigger_action("pensar")),
            ("💢 Irritada", lambda: self.controller.trigger_action("bravo")),
            ("🎵 Cantar", self._handle_sing_button),
        ]
        for idx, (label, cmd) in enumerate(emote_buttons):
            btn = ctk.CTkButton(
                self.emote_bar,
                text=label,
                height=28,
                 width=56,
                corner_radius=7,
                fg_color=theme.BG_SIDEBAR,
                hover_color=theme.ACCENT,
                text_color=theme.TEXT_PRIMARY,
                font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
                command=cmd,
            )
            btn.grid(row=0, column=idx, sticky="ew", padx=2, pady=4)

        self._ready = False
        self._closed = False
        self._pending_messages: list[str] = []
        self._lock = threading.Lock()

        self._form: Any = None
        self._webview: Any = None
        self._form_hwnd: int = 0
        self._sta_thread: threading.Thread | None = None

        self.viewport.bind("<Configure>", self._on_viewport_resize, add="+")
        self.after(120, self._start_webview_host)

    @property
    def is_ready(self) -> bool:
        return self._ready and not self._closed

    def set_mascot_mode_ui(self, active: bool) -> None:
        """No Modo Mascote PNG, oculta barras/bordas e ativa o fundo chroma-key #010203 transparente."""
        if active:
            self.top_bar.grid_remove()
            self.emote_bar.grid_remove()
            self.configure(fg_color="#010203", border_width=0, corner_radius=0)
            self.viewport.configure(fg_color="#010203", corner_radius=0)
            self.viewport.grid_configure(padx=0, pady=0)
        else:
            self.configure(
                fg_color=theme.BG_CHAT,
                border_width=1,
                border_color=theme.BORDER,
                corner_radius=14,
            )
            self.viewport.configure(fg_color=theme.BG_CHAT, corner_radius=10)
            self.viewport.grid_configure(padx=4, pady=2)
            self.top_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
            self.emote_bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(4, 8))
            self.mascot_btn.configure(
                text="📌 Fixar no Canto da Tela (Modo Mascote)",
                fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER,
            )
        self.send_message({"type": "mascot", "value": bool(active)})

    def _handle_toggle_mascot(self) -> None:
        if self._on_toggle_mascot:
            self._on_toggle_mascot()

    def _handle_sing_button(self) -> None:
        self.controller.trigger_action("cantar")
        if self._on_test_sing_speak:
            self._on_test_sing_speak()

    def _start_webview_host(self) -> None:
        if self._closed or self._sta_thread is not None:
            return
        try:
            self.viewport.update_idletasks()
            parent_hwnd = int(self.viewport.winfo_id())
            init_w = max(220, int(self.viewport.winfo_width()))
            init_h = max(300, int(self.viewport.winfo_height()))
        except Exception as exc:
            log.warning("Não foi possível obter HWND do painel de avatar: %s", exc)
            return

        self._sta_thread = threading.Thread(
            target=self._run_winforms_webview,
            args=(parent_hwnd, init_w, init_h),
            daemon=True,
            name="rin-live2d-webview",
        )
        self._sta_thread.start()

    def _run_winforms_webview(self, parent_hwnd: int, init_w: int, init_h: int) -> None:
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 2)

            import clr
            import webview

            dll_dir = Path(webview.__file__).resolve().parent / "lib"
            os.environ["PATH"] = (
                str(dll_dir)
                + os.pathsep
                + str(dll_dir / "runtimes" / "win-x64" / "native")
                + os.pathsep
                + os.environ.get("PATH", "")
            )

            clr.AddReference("System.Windows.Forms")
            clr.AddReference("System.Drawing")
            clr.AddReference("System")
            clr.AddReference(str(dll_dir / "Microsoft.Web.WebView2.Core.dll"))
            clr.AddReference(str(dll_dir / "Microsoft.Web.WebView2.WinForms.dll"))

            import System
            import System.Drawing as Drawing
            import System.Windows.Forms as WinForms
            from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind
            from Microsoft.Web.WebView2.WinForms import (
                CoreWebView2CreationProperties,
                WebView2,
            )

            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_CHILD = 0x40000000
            WS_VISIBLE = 0x10000000
            WS_CLIPSIBLINGS = 0x04000000
            WS_CLIPCHILDREN = 0x02000000

            user_data_dir = PROJECT_ROOT / "data" / "webview2_cache"
            user_data_dir.mkdir(parents=True, exist_ok=True)

            form = WinForms.Form()
            form.FormBorderStyle = getattr(WinForms.FormBorderStyle, "None")
            form.ShowInTaskbar = False
            form.StartPosition = WinForms.FormStartPosition.Manual
            form.Location = Drawing.Point(-3000, -3000)
            form.Size = Drawing.Size(init_w, init_h)
            form.BackColor = Drawing.Color.FromArgb(1, 2, 3)

            # Coluna central estreita na camada GDI estritamente atrás do tronco/cabeça opacos da Miku:
            # Permite clicar e arrastar diretamente na Miku (e usar scroll nela) sem vazar cliques
            # para a área de trabalho, mantendo todo o redor 100% transparente (#010203)!
            hit_brush = Drawing.SolidBrush(Drawing.Color.FromArgb(12, 16, 24))

            def on_form_paint(_sender: Any, args: Any) -> None:
                try:
                    w = int(form.ClientSize.Width)
                    h = int(form.ClientSize.Height)
                    rx = int(w * 0.43)
                    ry = int(h * 0.25)
                    rw = max(16, int(w * 0.14))
                    rh = max(40, int(h * 0.50))
                    args.Graphics.FillEllipse(hit_brush, rx, ry, rw, rh)
                except Exception:
                    pass

            form.Paint += on_form_paint
            form.Resize += lambda _s, _e: form.Invalidate()

            wv = WebView2()
            props = CoreWebView2CreationProperties()
            props.UserDataFolder = str(user_data_dir)
            wv.CreationProperties = props
            wv.Dock = WinForms.DockStyle.Fill
            # Alpha = 0 permite transparência real do WebView2 no Modo Mascote (sem fundo preto!)
            wv.DefaultBackgroundColor = Drawing.Color.FromArgb(0, 0, 0, 0)
            form.Controls.Add(wv)

            self._form = form
            self._webview = wv

            def _run_ui_safe(fn: Callable[[], None]) -> None:
                if self._dispatch_ui is not None:
                    self._dispatch_ui(fn)
                else:
                    try:
                        self.after(0, fn)
                    except Exception:
                        pass

            def on_web_message(_sender: Any, args: Any) -> None:
                try:
                    raw = args.TryGetWebMessageAsString()
                    data = json.loads(raw)
                    if not isinstance(data, dict):
                        return
                    msg_type = data.get("type")
                    if msg_type == "ready":
                        self._flush_pending_messages()
                    elif msg_type == "drag_start" and self._on_mascot_drag_start:
                        sx = int(data.get("screenX", 0))
                        sy = int(data.get("screenY", 0))
                        _run_ui_safe(lambda x=sx, y=sy: self._on_mascot_drag_start(x, y))
                    elif msg_type == "drag_move" and self._on_mascot_drag_move:
                        sx = int(data.get("screenX", 0))
                        sy = int(data.get("screenY", 0))
                        _run_ui_safe(lambda x=sx, y=sy: self._on_mascot_drag_move(x, y))
                    elif msg_type == "exit_mascot" and self._on_toggle_mascot:
                        _run_ui_safe(self._on_toggle_mascot)
                    elif msg_type == "toggle_mascot_chat" and self._on_toggle_mascot_chat:
                        _run_ui_safe(self._on_toggle_mascot_chat)
                    elif msg_type == "mascot_scale" and self._on_mascot_scale:
                        delta = int(data.get("delta", 0))
                        if delta != 0:
                            _run_ui_safe(lambda d=delta: self._on_mascot_scale(d))
                except Exception:
                    pass

            def on_init(_sender: Any, args: Any) -> None:
                if not args.IsSuccess:
                    log.error("Falha ao inicializar CoreWebView2: %s", args.InitializationException)
                    return
                try:
                    hwnd = int(form.Handle.ToInt64())
                    self._form_hwnd = hwnd
                    user32.SetParent(hwnd, parent_hwnd)
                    user32.SetWindowLongW(
                        hwnd,
                        GWL_STYLE,
                        WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN,
                    )
                    user32.MoveWindow(hwnd, 0, 0, init_w, init_h, True)

                    settings = wv.CoreWebView2.Settings
                    settings.AreDefaultContextMenusEnabled = False
                    settings.AreDevToolsEnabled = False
                    settings.IsStatusBarEnabled = False
                    settings.IsZoomControlEnabled = False

                    wv.CoreWebView2.SetVirtualHostNameToFolderMapping(
                        "rin.local",
                        str(PROJECT_ROOT),
                        CoreWebView2HostResourceAccessKind.Allow,
                    )
                    wv.CoreWebView2.WebMessageReceived += on_web_message

                    encoded_model = quote(self.controller.model_path, safe=":/._-()")
                    url = f"https://rin.local/src/avatar/web/index.html?model={encoded_model}&v=3"
                    wv.CoreWebView2.Navigate(url)

                    self._ready = True
                    self._flush_pending_messages()
                    _run_ui_safe(self._sync_viewport_after_init)
                except Exception:
                    log.exception("Erro ao configurar WebView2 do Avatar Live2D")

            def on_shown(_sender: Any, _args: Any) -> None:
                wv.EnsureCoreWebView2Async(None)

            wv.CoreWebView2InitializationCompleted += on_init
            form.Shown += on_shown

            self.controller.attach_widget(self)
            WinForms.Application.Run(form)
        except Exception as exc:
            log.warning("WebView2 Live2D indisponível neste ambiente: %s", exc)

    def _sync_viewport_after_init(self) -> None:
        if self._closed:
            return
        try:
            self._placeholder.place_forget()
            w = max(100, int(self.viewport.winfo_width()))
            h = max(100, int(self.viewport.winfo_height()))
            if self._form_hwnd:
                # 0x4014 = SWP_ASYNCWINDOWPOS (0x4000) | SWP_NOACTIVATE (0x0010) | SWP_NOZORDER (0x0004)
                ctypes.windll.user32.SetWindowPos(self._form_hwnd, 0, 0, 0, w, h, 0x4014)
        except Exception:
            pass

    def _on_viewport_resize(self, event: Any) -> None:
        if self._closed or not self._form_hwnd:
            return
        w = max(10, int(event.width))
        h = max(10, int(event.height))
        try:
            ctypes.windll.user32.SetWindowPos(self._form_hwnd, 0, 0, 0, w, h, 0x4014)
        except Exception:
            pass

    def send_message(self, payload: dict[str, Any]) -> None:
        """Envia comando JSON (`mouth`, `emotion`, `action`, `state`, `transform`, `pause`, `model`) para o WebView2."""
        if self._closed:
            return
        msg_str = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            if not self._ready or self._form is None or self._webview is None:
                if payload.get("type") != "mouth":
                    self._pending_messages.append(msg_str)
                return

        self._dispatch_to_webview(msg_str)

    def _flush_pending_messages(self) -> None:
        with self._lock:
            pending = list(self._pending_messages)
            self._pending_messages.clear()
        for msg_str in pending:
            self._dispatch_to_webview(msg_str)

    def _dispatch_to_webview(self, msg_str: str) -> None:
        form = self._form
        wv = self._webview
        if form is None or wv is None or self._closed:
            return
        try:
            import System

            def _post() -> None:
                try:
                    if not self._closed and wv.CoreWebView2 is not None:
                        wv.CoreWebView2.PostWebMessageAsString(msg_str)
                except Exception:
                    pass

            if form.IsHandleCreated and not form.IsDisposed:
                form.BeginInvoke(System.Action(_post))
        except Exception:
            pass

    def shutdown(self) -> None:
        """Fecha o formulário WinForms hospedado ao encerrar a janela."""
        if self._closed:
            return
        self._closed = True
        self._ready = False
        form = self._form
        if form is not None:
            try:
                import System

                if form.IsHandleCreated and not form.IsDisposed:
                    form.BeginInvoke(System.Action(form.Close))
            except Exception:
                pass
