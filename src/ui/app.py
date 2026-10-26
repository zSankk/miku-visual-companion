"""Janela principal da Rin (Modo Completo + Estúdio de Modelos + Modo Mascote no Canto da Tela)."""

from __future__ import annotations

import ctypes
import logging
import queue
import threading
from typing import Callable

import customtkinter as ctk

from src.avatar.live2d_widget import Live2DAvatarController, Live2DAvatarWidget
from src.avatar.vtube_studio import VTubeStudioController
from src.core.persona import PersonaError, load_persona
from src.core.router import ConversationRouter, RouterReply
from src.core.settings import Settings
from src.core.state import AgentState, Mode
from src.ui import theme
from src.ui.components import (
    ChatPanel,
    MemoryPanel,
    MessageBubble,
    ModelsStudioPanel,
    PrivacyPanel,
    StatusPanel,
    VoiceSettingsDialog,
)
from src.voice.mic_controller import AudioInputDevice, MicController, list_input_devices
from src.voice.stt import SpeechToText, VoiceSettings
from src.voice.tts import TextToSpeech

log = logging.getLogger(__name__)

_MODE_LABELS = {Mode.CASUAL: "Casual", Mode.DEV: "Dev Antigravity"}
_LABEL_TO_MODE = {v: k for k, v in _MODE_LABELS.items()}

_TAB_CHAT = "💬 Conversa"
_TAB_MODELS = "🎭 Modelos"
_TAB_MEMORY = "🧠 Memória"


class RinApp(ctk.CTk):
    def __init__(
        self,
        settings: Settings,
        router: ConversationRouter,
        mic: MicController,
        avatar: Live2DAvatarController | VTubeStudioController | None = None,
        tts: TextToSpeech | None = None,
        stt: SpeechToText | None = None,
    ) -> None:
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=theme.BG_APP)

        self.settings = settings
        self.router = router
        self.mic = mic
        self.voice_settings = VoiceSettings.load()
        if self.voice_settings.device_index is not None:
            self.mic.set_device(self.voice_settings.device_index)
        self.avatar = avatar or Live2DAvatarController(
            model_path=getattr(router.persona, "avatar_model_path", "")
        )
        self._avatar_visible = True
        self._mascot_mode = False
        self._mascot_chat_visible = False
        self._mascot_scale = 1.0
        self._saved_geometry = "1280x780"
        self._drag_offset_x = 0
        self._drag_offset_y = 0

        self.tts = tts or TextToSpeech(
            voice=self.voice_settings.tts_voice,
            enabled=self.voice_settings.tts_enabled,
            volume=self.voice_settings.tts_volume,
            base_rate_pct=self.voice_settings.tts_rate_pct,
            pitch_hz=self.voice_settings.tts_pitch_hz,
            tts_provider=self.voice_settings.tts_provider,
            miku_model=self.voice_settings.miku_model,
            miku_phonetic_ptbr=self.voice_settings.miku_phonetic_ptbr,
            miku_timeout_s=self.voice_settings.miku_timeout_s,
            on_start=lambda: self._run_on_ui(lambda: self.privacy.set_tts_speaking(True)),
            on_end=lambda: self._run_on_ui(lambda: self.privacy.set_tts_speaking(False)),
            on_mouth_open=self.avatar.set_mouth_open,
        )
        self.stt = stt or SpeechToText(
            mic=self.mic,
            on_transcript=lambda text: self._run_on_ui(lambda t=text: self._on_voice_transcript(t)),
            on_level=lambda lvl: self._run_on_ui(lambda l=lvl: self.privacy.set_level(l)),
            model_size=self.voice_settings.whisper_model,
            energy_threshold=self.voice_settings.energy_threshold,
            silence_duration_s=self.voice_settings.silence_duration_s,
        )

        # Fila para executar código na thread da UI a partir de threads de trabalho
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._session_id = 0
        self._busy = False
        self._typing_job: str | None = None

        self.title(f"{router.persona.name} · Virtual Companion")
        self.geometry("1280x780")
        self.minsize(920, 580)

        self._build_layout()
        self._bind_shortcuts()

        # Carrega microfones disponíveis e estado inicial
        self.privacy.set_devices(list_input_devices(), selected_index=self.mic.device_index)
        self.mic.add_listener(self._on_mic_state_changed)
        self.privacy.set_muted(self.mic.is_muted)
        self.privacy.set_tts_enabled(self.tts.enabled)
        self._update_idle_or_listening_state()
        self.status.set_emotion(router.persona.default_emotion)
        self.avatar.set_emotion(router.persona.default_emotion)
        self._apply_mode(router.mode)
        self._announce_session(first=True)

        if not self.mic.is_muted:
            try:
                self.stt.start()
            except Exception as exc:
                log.warning("Não foi possível iniciar o STT automaticamente: %s", exc)
        else:
            # Pré-carrega o Faster-Whisper local em background enquanto está mutado
            self.stt.preload_model_async()

        # Pré-aquece o modelo RVC local da Miku em background
        self.tts.preload_async()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain_ui_queue)
        self.after(200, self.input.focus_set)

    # ================================================================ layout
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ----------------------------------------------------------- sidebar
        self.sidebar = ctk.CTkFrame(self, width=285, corner_radius=0, fg_color=theme.BG_SIDEBAR)
        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(
            self.sidebar, text=self.router.persona.name, text_color=theme.ACCENT,
            font=ctk.CTkFont(theme.FONT_FAMILY, 34, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(18, 0))
        ctk.CTkLabel(
            self.sidebar, text="Virtual Companion · Desktop", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12), anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        self.privacy = PrivacyPanel(
            self.sidebar,
            on_toggle=self._toggle_mic,
            on_device_select=self._on_mic_device_selected,
            on_refresh_devices=self._refresh_mic_devices,
            on_open_settings=self._open_voice_settings,
            on_toggle_tts_mute=self._toggle_tts_mute,
            on_stop_tts=self._stop_tts_speech,
        )
        self.privacy.grid(row=2, column=0, sticky="ew", padx=14)

        mode_box = ctk.CTkFrame(
            self.sidebar, fg_color=theme.BG_CARD, corner_radius=14,
            border_width=1, border_color=theme.BORDER,
        )
        mode_box.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctk.CTkLabel(
            mode_box, text="MODO DE OPERAÇÃO", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 4))
        self.mode_selector = ctk.CTkSegmentedButton(
            mode_box, values=list(_MODE_LABELS.values()), command=self._on_mode_selected,
            selected_color=theme.ACCENT, selected_hover_color=theme.ACCENT_HOVER,
            fg_color=theme.BG_SIDEBAR, unselected_color=theme.BG_SIDEBAR,
            unselected_hover_color=theme.BORDER, text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"), height=32,
        )
        self.mode_selector.pack(fill="x", padx=14)
        self.mode_hint = ctk.CTkLabel(
            mode_box, text="", text_color=theme.TEXT_MUTED, justify="left", anchor="w",
            wraplength=235, font=ctk.CTkFont(theme.FONT_FAMILY, 11),
        )
        self.mode_hint.pack(fill="x", padx=14, pady=(4, 10))

        ctk.CTkButton(
            self.sidebar, text="+  Nova Sessão", height=36, corner_radius=10,
            fg_color="transparent", border_width=1, border_color=theme.BORDER,
            hover_color=theme.BG_CARD, text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"), command=self._new_session,
        ).grid(row=4, column=0, sticky="ew", padx=14, pady=(10, 0))

        self.sidebar_mascot_btn = ctk.CTkButton(
            self.sidebar,
            text="📌 Fixar no Canto da Tela (Modo Mascote)",
            height=36,
            corner_radius=10,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._toggle_mascot_mode,
        )
        self.sidebar_mascot_btn.grid(row=5, column=0, sticky="ew", padx=14, pady=(8, 0))

        self.avatar_toggle_btn = ctk.CTkButton(
            self.sidebar,
            text="Ocultar Avatar (Economizar GPU)",
            height=34,
            corner_radius=10,
            fg_color=theme.BG_CARD,
            border_width=1,
            border_color=theme.BORDER,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._toggle_avatar_visibility,
        )
        self.avatar_toggle_btn.grid(row=6, column=0, sticky="ew", padx=14, pady=(6, 0))

        brain_name = getattr(self.router.brain, "name", "?")
        self.footer = ctk.CTkLabel(
            self.sidebar, text=f"Cérebro: {brain_name}\nAtalhos: Ctrl+N nova sessão · Ctrl+D modo",
            text_color=theme.TEXT_MUTED, justify="left", anchor="w", wraplength=250,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
        )
        self.footer.grid(row=8, column=0, sticky="sw", padx=20, pady=12)

        # -------------------------------------------------------------- main
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.grid(row=0, column=1, sticky="nsew", padx=18, pady=18)
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(1, weight=0)
        self.main_area.grid_rowconfigure(2, weight=1)

        self.status = StatusPanel(self.main_area)
        self.status.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        # Barra de Abas ("💬 Conversa" | "🎭 Modelos")
        self.nav_bar = ctk.CTkFrame(self.main_area, fg_color="transparent")
        self.nav_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.nav_bar.grid_columnconfigure(0, weight=1)

        self.nav_tabs = ctk.CTkSegmentedButton(
            self.nav_bar,
            values=[_TAB_CHAT, _TAB_MODELS, _TAB_MEMORY],
            command=self._on_tab_selected,
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            fg_color=theme.BG_CARD,
            unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13, "bold"),
            height=36,
        )
        self.nav_tabs.set(_TAB_CHAT)
        self.nav_tabs.grid(row=0, column=0, sticky="w")

        # Aba 1: Conversa (Chat)
        self.chat = ChatPanel(self.main_area, rin_name=self.router.persona.name)
        self.chat.grid(row=2, column=0, sticky="nsew")

        # Aba 2: "🎭 Modelos" (Estúdio de Modelos & Emotes Live2D)
        if isinstance(self.avatar, Live2DAvatarController):
            self.models_studio: ModelsStudioPanel | None = ModelsStudioPanel(
                self.main_area,
                avatar=self.avatar,
                on_test_sing_speak=self._test_sing_speak,
            )
        else:
            self.models_studio = None

        # Aba 3: "🧠 Memória" (Memória de Longo Prazo SQLite)
        self.memory_panel = MemoryPanel(
            self.main_area,
            memory_store=self.router.long_term,
            on_archive_session=self._archive_and_new_session,
            on_status_message=lambda msg: self.chat.add_system(msg),
        )

        # Painel Direito: Renderizador Live2D Embutido + Soundboard de Emotes
        if isinstance(self.avatar, Live2DAvatarController):
            self.avatar_panel: Live2DAvatarWidget | None = Live2DAvatarWidget(
                self.main_area,
                controller=self.avatar,
                width=350,
                on_test_sing_speak=self._test_sing_speak,
                on_toggle_mascot=self._toggle_mascot_mode,
                on_mascot_drag_start=self._start_mascot_drag_screen,
                on_mascot_drag_move=self._do_mascot_drag_screen,
                on_toggle_mascot_chat=self._toggle_mascot_chat_balloon,
                on_mascot_scale=self._scale_mascot_size,
                dispatch_ui=self._run_on_ui,
            )
            self.avatar_panel.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(12, 0))
        else:
            self.avatar_panel = None

        # Barra de entrada de mensagem (Modo Completo)
        self.input_bar = ctk.CTkFrame(
            self.main_area, fg_color=theme.BG_INPUT, corner_radius=14,
            border_width=1, border_color=theme.BORDER,
        )
        self.input_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.input_bar.grid_columnconfigure(0, weight=1)

        self.input = ctk.CTkTextbox(
            self.input_bar, height=64, fg_color="transparent", wrap="word",
            font=ctk.CTkFont(theme.FONT_FAMILY, 14), text_color=theme.TEXT_PRIMARY,
        )
        self.input.grid(row=0, column=0, sticky="ew", padx=(10, 6), pady=8)
        self.input.bind("<Return>", self._on_enter)

        self.send_button = ctk.CTkButton(
            self.input_bar, text="Enviar", width=96, height=44, corner_radius=10,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13, "bold"), command=self._send,
        )
        self.send_button.grid(row=0, column=1, padx=(0, 10), pady=8)

        self.shortcut_hint = ctk.CTkLabel(
            self.main_area,
            text="Enter envia · Shift+Enter quebra linha · clique direito em uma mensagem para copiar",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 10),
        )
        self.shortcut_hint.grid(row=4, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))

        # -------------------------------------------------------------- Overlay do Modo Mascote
        # Pílula de Controle Nativa (GDI) abaixo dos pés da Miku: 100% clicável e arrastável
        # enquanto o fundo ao redor da personagem permanece 100% transparente (#010203)!
        self.mascot_drag_bar = ctk.CTkFrame(
            self.main_area,
            fg_color=theme.BG_SIDEBAR,
            corner_radius=12,
            border_width=1,
            border_color=theme.ACCENT,
            height=34,
        )
        self.mascot_drag_bar.grid_columnconfigure(0, weight=1)

        self.mascot_drag_lbl = ctk.CTkLabel(
            self.mascot_drag_bar,
            text="✥ Mover",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
            cursor="fleur",
        )
        self.mascot_drag_lbl.grid(row=0, column=0, sticky="ew", padx=(8, 4), pady=4)

        self.mascot_zoom_out_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="➖",
            width=26,
            height=24,
            corner_radius=6,
            fg_color=theme.BG_CARD,
            hover_color=theme.ACCENT,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=lambda: self._scale_mascot_size(-1),
        )
        self.mascot_zoom_out_btn.grid(row=0, column=1, padx=2, pady=4)

        self.mascot_zoom_in_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="➕",
            width=26,
            height=24,
            corner_radius=6,
            fg_color=theme.BG_CARD,
            hover_color=theme.ACCENT,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=lambda: self._scale_mascot_size(1),
        )
        self.mascot_zoom_in_btn.grid(row=0, column=2, padx=2, pady=4)

        self.mascot_mic_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="🔇" if self.mic.is_muted else "🎙️",
            width=28,
            height=24,
            corner_radius=6,
            fg_color=theme.MIC_OFF if self.mic.is_muted else theme.MIC_ON,
            command=self._toggle_mic,
        )
        self.mascot_mic_btn.grid(row=0, column=3, padx=2, pady=4)

        self.mascot_tts_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="🔊" if self.tts.enabled else "🔈",
            width=28,
            height=24,
            corner_radius=6,
            fg_color=theme.ACCENT if self.tts.enabled else theme.BG_CARD,
            hover_color=theme.ACCENT_HOVER,
            command=self._toggle_tts_mute,
        )
        self.mascot_tts_btn.grid(row=0, column=4, padx=2, pady=4)

        self.mascot_chat_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="💬",
            width=28,
            height=24,
            corner_radius=6,
            fg_color=theme.BG_CARD,
            hover_color=theme.ACCENT,
            command=self._toggle_mascot_chat_balloon,
        )
        self.mascot_chat_btn.grid(row=0, column=5, padx=2, pady=4)

        self.mascot_restore_btn = ctk.CTkButton(
            self.mascot_drag_bar,
            text="🗖 Janela",
            width=64,
            height=24,
            corner_radius=6,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._exit_mascot_mode,
        )
        self.mascot_restore_btn.grid(row=0, column=6, padx=(2, 6), pady=4)

        for w in (self.mascot_drag_bar, self.mascot_drag_lbl):
            w.bind("<ButtonPress-1>", self._start_mascot_drag)
            w.bind("<B1-Motion>", self._do_mascot_drag)

        self.mascot_balloon = ctk.CTkFrame(
            self.main_area,
            fg_color=theme.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=theme.ACCENT,
        )
        self.mascot_balloon.grid_columnconfigure(0, weight=1)

        self.mascot_bubble_lbl = ctk.CTkLabel(
            self.mascot_balloon,
            text=f"💬 {self.router.persona.name}: Oi! Estou aqui no cantinho da sua tela acompanhando você!",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            justify="left",
            anchor="w",
            wraplength=325,
        )
        self.mascot_bubble_lbl.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(8, 4))
        self.mascot_bubble_lbl.bind("<ButtonPress-1>", self._start_mascot_drag)
        self.mascot_bubble_lbl.bind("<B1-Motion>", self._do_mascot_drag)

        self.mascot_entry = ctk.CTkEntry(
            self.mascot_balloon,
            placeholder_text=f"Fale com a {self.router.persona.name}...",
            height=30,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self.mascot_entry.grid(row=1, column=0, sticky="ew", padx=(8, 4), pady=(2, 8))
        self.mascot_entry.bind("<Return>", lambda _e: self._send_from_mascot())

        self.mascot_send_btn = ctk.CTkButton(
            self.mascot_balloon,
            text="➤",
            width=36,
            height=30,
            corner_radius=8,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            command=self._send_from_mascot,
        )
        self.mascot_send_btn.grid(row=1, column=1, padx=(0, 8), pady=(2, 8))

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-m>", lambda e: self._toggle_mic())
        self.bind_all("<Control-n>", lambda e: self._new_session())
        self.bind_all("<Control-d>", lambda e: self._toggle_mode())
        self.bind_all("<Escape>", lambda e: self._exit_mascot_if_active())

    # ============================================================ Abas & Modo Mascote
    def _on_tab_selected(self, tab_label: str) -> None:
        if tab_label == _TAB_MODELS and self.models_studio is not None:
            self.chat.grid_remove()
            if hasattr(self, "memory_panel"):
                self.memory_panel.grid_remove()
            self.models_studio.refresh_models_gallery()
            self.models_studio.grid(row=2, column=0, sticky="nsew")
        elif tab_label == _TAB_MEMORY and hasattr(self, "memory_panel"):
            self.chat.grid_remove()
            if self.models_studio is not None:
                self.models_studio.grid_remove()
            self.memory_panel.refresh()
            self.memory_panel.grid(row=2, column=0, sticky="nsew")
        else:
            if self.models_studio is not None:
                self.models_studio.grid_remove()
            if hasattr(self, "memory_panel"):
                self.memory_panel.grid_remove()
            self.chat.grid(row=2, column=0, sticky="nsew")

    def _toggle_mascot_mode(self) -> None:
        """Alterna entre a Janela Completa e o Modo Mascote Compacto Sempre no Topo no Canto da Tela."""
        if not self._mascot_mode:
            self._enter_mascot_mode()
        else:
            self._exit_mascot_mode()

    def _get_top_hwnd(self) -> int:
        try:
            inner = int(self.winfo_id())
            parent = int(ctypes.windll.user32.GetParent(inner))
            return parent if parent else inner
        except Exception:
            return 0

    def _set_win32_borderless_transparent(self, active: bool) -> None:
        """Altera o estilo da janela via Win32 sem chamar self.overrideredirect()
        (evita que o Tcl/Tk destrua o HWND pai e trave o WebView2 filho ao voltar à janela)."""
        hwnd = self._get_top_hwnd()
        if not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_CAPTION = 0x00C00000
            WS_THICKFRAME = 0x00040000
            WS_SYSMENU = 0x00080000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            FRAME_BITS = WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
            # SWP_NOMOVE(0x2) | SWP_NOSIZE(0x1) | SWP_NOZORDER(0x4) | SWP_FRAMECHANGED(0x20) | SWP_ASYNCWINDOWPOS(0x4000)
            SWP_FLAGS = 0x4027

            style = int(user32.GetWindowLongW(hwnd, GWL_STYLE))
            if active:
                self._saved_win32_style = style
                user32.SetWindowLongW(hwnd, GWL_STYLE, style & ~FRAME_BITS)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
                # Estende a folha transparente DWM na área cliente para o WebView2 Alpha=0 não ter fundo preto
                class _MARGINS(ctypes.Structure):
                    _fields_ = [
                        ("cxLeftWidth", ctypes.c_int),
                        ("cxRightWidth", ctypes.c_int),
                        ("cyTopHeight", ctypes.c_int),
                        ("cyBottomHeight", ctypes.c_int),
                    ]

                margins = _MARGINS(-1, -1, -1, -1)
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            else:
                restored = getattr(self, "_saved_win32_style", style | FRAME_BITS)
                user32.SetWindowLongW(hwnd, GWL_STYLE, restored)
                user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_FLAGS)
                class _MARGINS(ctypes.Structure):
                    _fields_ = [
                        ("cxLeftWidth", ctypes.c_int),
                        ("cxRightWidth", ctypes.c_int),
                        ("cyTopHeight", ctypes.c_int),
                        ("cyBottomHeight", ctypes.c_int),
                    ]

                margins = _MARGINS(0, 0, 0, 0)
                ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        except Exception as exc:
            log.debug("Ajuste Win32 borderless ignorado: %s", exc)

    def _enter_mascot_mode(self) -> None:
        if self._mascot_mode:
            return
        self._mascot_mode = True
        self._mascot_chat_visible = False
        try:
            self._saved_geometry = self.geometry()
        except Exception:
            self._saved_geometry = "1280x780"

        # Garante que o avatar esteja visível e ativo ao entrar no Modo Mascote
        if not self._avatar_visible:
            self._toggle_avatar_visibility()

        self.sidebar.grid_remove()
        self.status.grid_remove()
        self.nav_bar.grid_remove()
        self.chat.grid_remove()
        if self.models_studio is not None:
            self.models_studio.grid_remove()
        self.input_bar.grid_remove()
        self.shortcut_hint.grid_remove()
        self.mascot_drag_bar.grid_remove()
        self.mascot_balloon.grid_remove()

        # Fundo chroma-key #010203 vazado pelo Windows + WebView2 Alpha=0 para ficar 100% sem fundo preto!
        self.configure(fg_color="#010203")
        self.main_area.configure(fg_color="#010203")
        self.main_area.grid_configure(padx=0, pady=0)
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(1, weight=0)
        self.main_area.grid_rowconfigure(0, weight=0)
        self.main_area.grid_rowconfigure(1, weight=1)
        self.main_area.grid_rowconfigure(2, weight=0)

        if self.avatar_panel is not None:
            self.avatar_panel.set_mascot_mode_ui(True)
            self.avatar_panel.grid(row=1, column=0, rowspan=1, sticky="nsew", padx=0, pady=0)

        # Exibe a pílula compacta de controles (Mover, -/+, Mic, Voz, Chat, Janela) sob os pés da Miku
        self.mascot_drag_bar.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 4))

        mascot_w = max(250, int(340 * self._mascot_scale))
        mascot_h = max(350, int(510 * self._mascot_scale))
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        pos_x = max(10, screen_w - mascot_w - 16)
        pos_y = max(10, screen_h - mascot_h - 48)

        self.minsize(240, 320)
        self.attributes("-topmost", True)
        try:
            self.attributes("-alpha", 1.0)
            self.wm_attributes("-transparentcolor", "#010203")
        except Exception:
            pass
        self._set_win32_borderless_transparent(True)
        self.geometry(f"{mascot_w}x{mascot_h}+{pos_x}+{pos_y}")

    def _scale_mascot_size(self, delta: int) -> None:
        """Aumenta (+1) ou diminui (-1) o tamanho da Miku na tela no Modo Mascote."""
        if not self._mascot_mode:
            return
        step = 0.14 if delta > 0 else -0.14
        self._mascot_scale = max(0.65, min(1.85, round(self._mascot_scale + step, 2)))
        mascot_w = max(250, int(340 * self._mascot_scale))
        extra_h = 84 if self._mascot_chat_visible else 0
        mascot_h = max(350, int(510 * self._mascot_scale)) + extra_h
        cur_x = self.winfo_x()
        cur_y = self.winfo_y()
        self.geometry(f"{mascot_w}x{mascot_h}+{cur_x}+{cur_y}")

    def _toggle_mascot_chat_balloon(self) -> None:
        """Mostra ou oculta o balão flutuante de chat quando no Modo Mascote PNG."""
        if not self._mascot_mode:
            return
        self._mascot_chat_visible = not self._mascot_chat_visible
        mascot_w = max(250, int(340 * self._mascot_scale))
        base_h = max(350, int(510 * self._mascot_scale))
        cur_x = self.winfo_x()
        cur_y = self.winfo_y()
        if self._mascot_chat_visible:
            self.mascot_balloon.grid(row=3, column=0, sticky="ew", padx=6, pady=(2, 6))
            self.geometry(f"{mascot_w}x{base_h + 84}+{cur_x}+{cur_y}")
            self.mascot_entry.focus_set()
        else:
            self.mascot_balloon.grid_remove()
            self.geometry(f"{mascot_w}x{base_h}+{cur_x}+{cur_y}")

    def _exit_mascot_if_active(self) -> None:
        if self._mascot_mode:
            self._exit_mascot_mode()

    def _exit_mascot_mode(self) -> None:
        if not self._mascot_mode:
            return
        self._mascot_mode = False
        self._mascot_chat_visible = False

        self._set_win32_borderless_transparent(False)
        try:
            self.wm_attributes("-transparentcolor", "")
            self.attributes("-alpha", 1.0)
        except Exception:
            pass
        self.attributes("-topmost", False)
        self.configure(fg_color=theme.BG_APP)
        self.main_area.configure(fg_color="transparent")
        self.minsize(920, 580)
        self.geometry(self._saved_geometry)

        self.mascot_drag_bar.grid_remove()
        self.mascot_balloon.grid_remove()

        self.sidebar.grid(row=0, column=0, sticky="nsw")
        self.main_area.grid_configure(padx=18, pady=18)
        self.main_area.grid_columnconfigure(0, weight=1)
        self.main_area.grid_columnconfigure(1, weight=0)
        self.main_area.grid_rowconfigure(0, weight=0)
        self.main_area.grid_rowconfigure(1, weight=0)
        self.main_area.grid_rowconfigure(2, weight=1)

        self.status.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        self.nav_bar.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._on_tab_selected(self.nav_tabs.get())

        if self.avatar_panel is not None:
            self.avatar_panel.set_mascot_mode_ui(False)
            if self._avatar_visible:
                self.avatar_panel.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(12, 0))

        self.input_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.shortcut_hint.grid(row=4, column=0, columnspan=2, sticky="w", padx=4, pady=(4, 0))

    def _start_mascot_drag(self, event) -> None:
        self._drag_offset_x = event.x_root - self.winfo_x()
        self._drag_offset_y = event.y_root - self.winfo_y()

    def _do_mascot_drag(self, event) -> None:
        if not self._mascot_mode:
            return
        new_x = event.x_root - self._drag_offset_x
        new_y = event.y_root - self._drag_offset_y
        self.geometry(f"+{new_x}+{new_y}")

    def _start_mascot_drag_screen(self, screen_x: int, screen_y: int) -> None:
        self._drag_offset_x = int(screen_x) - self.winfo_x()
        self._drag_offset_y = int(screen_y) - self.winfo_y()

    def _do_mascot_drag_screen(self, screen_x: int, screen_y: int) -> None:
        if not self._mascot_mode:
            return
        new_x = int(screen_x) - self._drag_offset_x
        new_y = int(screen_y) - self._drag_offset_y
        self.geometry(f"+{new_x}+{new_y}")

    def _send_from_mascot(self) -> None:
        if self._busy:
            return
        text = self.mascot_entry.get().strip()
        if not text:
            return
        self.mascot_entry.delete(0, "end")
        self._submit_message(text, from_voice=False)

    # ============================================================ threading
    def _run_on_ui(self, fn: Callable[[], None]) -> None:
        self._ui_queue.put(fn)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception:
            log.exception("Erro ao processar evento da UI")
        self.after(50, self._drain_ui_queue)

    # ============================================================ microfone & voz
    def _toggle_mic(self) -> None:
        self.mic.toggle()

    def _on_mic_state_changed(self, muted: bool) -> None:
        def _update() -> None:
            self.privacy.set_muted(muted)
            self.mascot_mic_btn.configure(
                fg_color=theme.MIC_OFF if muted else theme.MIC_ON,
                text="🔇" if muted else "🎙️",
            )
            if not self._busy:
                self._update_idle_or_listening_state()

        self._run_on_ui(_update)

    def _on_mic_device_selected(self, device_index: int | None) -> None:
        self.mic.set_device(device_index)
        self.voice_settings.device_index = device_index
        self.voice_settings.save()

    def _open_voice_settings(self) -> None:
        VoiceSettingsDialog(
            self,
            mic=self.mic,
            stt=self.stt,
            tts=self.tts,
            voice_settings=self.voice_settings,
            on_settings_changed=self._sync_voice_ui,
            dispatch_ui=self._run_on_ui,
        )

    def _sync_voice_ui(self) -> None:
        self.privacy.set_devices(list_input_devices(), selected_index=self.mic.device_index)
        self.privacy.set_tts_enabled(self.tts.enabled)
        if hasattr(self, "mascot_tts_btn"):
            self.mascot_tts_btn.configure(
                text="🔊" if self.tts.enabled else "🔈",
                fg_color=theme.ACCENT if self.tts.enabled else theme.BG_CARD,
            )

    def _toggle_tts_mute(self) -> None:
        self.tts.enabled = not self.tts.enabled
        self.voice_settings.tts_enabled = self.tts.enabled
        self.voice_settings.save()
        self.privacy.set_tts_enabled(self.tts.enabled)
        if hasattr(self, "mascot_tts_btn"):
            self.mascot_tts_btn.configure(
                text="🔊" if self.tts.enabled else "🔈",
                fg_color=theme.ACCENT if self.tts.enabled else theme.BG_CARD,
            )
        if not self.tts.enabled:
            self._stop_tts_speech()

    def _stop_tts_speech(self) -> None:
        """Corta a fala da Rin imediatamente e volta ao estado Inativa/Ouvindo."""
        self.tts.stop()
        self.avatar.set_mouth_open(0.0)
        self.privacy.set_tts_speaking(False)
        if self._busy and getattr(self, "_typing_done", True):
            self._finish_turn()

    def _test_sing_speak(self) -> None:
        """Dispara uma demonstração de canto/fala Vocaloid sincronizada a 60 FPS com o Live2D."""
        if self._busy:
            return
        self._set_agent_state(AgentState.FALANDO)
        self.avatar.set_emotion("feliz")
        if hasattr(self.avatar, "trigger_action"):
            self.avatar.trigger_action("cantar")
        session = self._session_id
        self.tts.speak(
            f"La la la! Oi, eu sou a {self.router.persona.name}! Olha como minha voz e meus movimentos estão sincronizados!",
            "feliz",
            on_done=lambda s=session: self._run_on_ui(lambda: self._update_idle_or_listening_state()),
        )

    def _toggle_avatar_visibility(self) -> None:
        """Esconde/mostra o painel da personagem e pausa/retoma o WebGL (app.ticker.stop())."""
        self._avatar_visible = not self._avatar_visible
        if self.avatar_panel is not None:
            if self._avatar_visible:
                if self._mascot_mode:
                    self.avatar_panel.grid(row=1, column=0, sticky="nsew", padx=0)
                else:
                    self.avatar_panel.grid(row=1, column=1, rowspan=2, sticky="nsew", padx=(12, 0))
            else:
                self.avatar_panel.grid_remove()

        if hasattr(self.avatar, "set_gpu_paused"):
            self.avatar.set_gpu_paused(not self._avatar_visible)

        if self._avatar_visible:
            self.avatar_toggle_btn.configure(
                text="Ocultar Avatar (Economizar GPU)",
                fg_color=theme.BG_CARD,
            )
        else:
            self.avatar_toggle_btn.configure(
                text="Mostrar Avatar (Live2D)",
                fg_color=theme.ACCENT,
            )

    def _set_agent_state(self, state: AgentState) -> None:
        self.status.set_state(state)
        if hasattr(self.avatar, "set_state"):
            self.avatar.set_state(state)

    def _refresh_mic_devices(self) -> list[AudioInputDevice]:
        return list_input_devices()

    def _update_idle_or_listening_state(self) -> None:
        if self.mic.is_muted:
            self._set_agent_state(AgentState.INATIVA)
        else:
            self._set_agent_state(AgentState.OUVINDO)

    def _on_voice_transcript(self, text: str) -> None:
        """Recebe a fala reconhecida pelo microfone e envia para a Rin."""
        if self._busy:
            return
        self._submit_message(text, from_voice=True)

    # ============================================================ ações
    def _on_mode_selected(self, label: str) -> None:
        self._apply_mode(_LABEL_TO_MODE.get(label, Mode.CASUAL))

    def _toggle_mode(self) -> None:
        self._apply_mode(Mode.DEV if self.router.mode is Mode.CASUAL else Mode.CASUAL)

    def _apply_mode(self, mode: Mode) -> None:
        self.router.set_mode(mode)
        self.mode_selector.set(_MODE_LABELS[mode])
        self.status.set_mode(mode)
        if mode is Mode.CASUAL:
            hint = "Conversa livre com o modelo rápido (custo zero/mínimo)."
        elif self.router.bridge.is_available():
            hint = "Tarefas de dev delegadas ao Antigravity via MCP."
        else:
            hint = f"Ponte MCP ainda não conectada (fase futura). {self.router.persona.name} responde como assistente dev."
        self.mode_hint.configure(text=hint)

    def _announce_session(self, first: bool = False) -> None:
        brain = getattr(self.router.brain, "name", "?")
        self.chat.add_system(
            f"{'Sessão iniciada' if first else 'Nova sessão'} · Cérebro: {brain} · Modo: {self.router.mode.label}"
        )
        if not self.settings.has_api_key:
            self.chat.add_system("Sem GEMINI_API_KEY no .env: respostas simuladas (modo offline).")

    def _archive_and_new_session(self) -> str | None:
        """Gera resumo conciso com IA, salva em summaries e limpa a sessão."""
        summary = self.router.archive_and_new_session()
        self._new_session(skip_router=True)
        if summary:
            self.chat.add_system(f"Resumo da conversa anterior arquivado na memória: {summary}")
        return summary

    def _new_session(self, skip_router: bool = False) -> None:
        self._session_id += 1  # respostas pendentes da sessão anterior serão descartadas
        self._cancel_typing()
        self.tts.stop()
        self._busy = False
        self.stt.paused = False
        self._set_input_enabled(True)

        persona = None
        try:
            persona = load_persona(self.settings.persona_path)
        except PersonaError as exc:
            log.error("Falha ao recarregar persona: %s", exc)

        if not skip_router:
            self.router.new_session(persona)
        elif persona is not None:
            self.router.persona = persona
        self.chat.clear()
        self._update_idle_or_listening_state()
        self.status.set_emotion(self.router.persona.default_emotion)
        self.avatar.set_emotion(self.router.persona.default_emotion)
        if hasattr(self.avatar, "set_model_path"):
            self.avatar.set_model_path(self.router.persona.avatar_model_path, persist=False)
        self._announce_session()
        if persona is None:
            self.chat.add_message("error", "persona.yaml inválido; mantive a persona anterior. Veja o log.")
        self.input.focus_set()

    def _on_enter(self, event):
        if event.state & 0x0001:  # Shift pressionado -> quebra de linha
            return None
        self._send()
        return "break"

    def _send(self) -> None:
        if self._busy:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self.input.delete("1.0", "end")
        self._submit_message(text, from_voice=False)

    def _submit_message(self, text: str, from_voice: bool = False) -> None:
        display = f"🎙️ {text}" if from_voice else text
        self.chat.add_message("user", display)
        self.mascot_bubble_lbl.configure(text=f"💭 Pensando na resposta para: \"{text[:55]}\"...")

        # Se o usuário mandou cumprimento ("oi", "olá", "bom dia"), já acena imediatamente!
        from src.core.emotion_parser import infer_action_from_turn

        early_action = infer_action_from_turn(text, "", "neutra")
        if early_action == "acenar" and hasattr(self.avatar, "trigger_action"):
            self.avatar.trigger_action("acenar")

        self._busy = True
        self.stt.paused = True
        self._set_input_enabled(False)
        self._set_agent_state(AgentState.PENSANDO)

        session = self._session_id
        threading.Thread(target=self._worker, args=(text, session), daemon=True).start()

    def _worker(self, text: str, session: int) -> None:
        try:
            reply = self.router.handle(text)
            pre_pcm = None
            if session == self._session_id and self.tts.enabled and hasattr(self.tts, "prepare_speech_pcm"):
                pre_pcm = self.tts.prepare_speech_pcm(reply.text, reply.emotion)
        except Exception as exc:
            log.exception("Erro ao gerar resposta")
            self._run_on_ui(lambda e=exc: self._on_error(e, session))
            return
        self._run_on_ui(lambda r=reply, p=pre_pcm: self._on_reply(r, session, p))

    def _on_reply(self, reply: RouterReply, session: int, pre_pcm=None) -> None:
        if session != self._session_id:
            return
        self.footer.configure(
            text=f"Cérebro: {reply.source}\nAtalhos: Ctrl+N nova sessão · Ctrl+D modo"
        )
        self.status.set_emotion(reply.emotion)
        self.avatar.set_emotion(reply.emotion)
        if reply.action and hasattr(self.avatar, "trigger_action"):
            self.avatar.trigger_action(reply.action)
        self._set_agent_state(AgentState.FALANDO)
        self.mascot_bubble_lbl.configure(text=f"💬 {self.router.persona.name}: {reply.text}")
        bubble = self.chat.add_message("rin", "", reply.emotion)
        bubble.full_text = reply.text
        self._typing_done = False
        self._tts_done = not self.tts.enabled
        if pre_pcm is not None and hasattr(self.tts, "play_prepared_pcm"):
            self.tts.play_prepared_pcm(
                pre_pcm,
                on_done=lambda s=session: self._run_on_ui(lambda: self._on_tts_finished(s)),
            )
        else:
            self.tts.speak(
                reply.text,
                reply.emotion,
                on_done=lambda s=session: self._run_on_ui(lambda: self._on_tts_finished(s)),
            )
        self._type_out(bubble, reply.text, session)

    def _on_tts_finished(self, session: int) -> None:
        if session != self._session_id:
            return
        self._tts_done = True
        if self._typing_done:
            self._finish_turn()

    def _type_out(self, bubble: MessageBubble, text: str, session: int, pos: int = 0) -> None:
        """Efeito de digitação (estado 'Falando'); limita a ~2,5s por resposta."""
        if session != self._session_id:
            return
        step = max(2, len(text) // 120)
        pos = min(len(text), pos + step)
        bubble.set_text(text[:pos])
        if pos < len(text):
            self._typing_job = self.after(18, self._type_out, bubble, text, session, pos)
        else:
            self._typing_job = None
            self._typing_done = True
            self.chat.scroll_to_bottom()
            if self._tts_done:
                self._finish_turn()

    def _cancel_typing(self) -> None:
        if self._typing_job:
            self.after_cancel(self._typing_job)
            self._typing_job = None

    def _on_error(self, exc: Exception, session: int) -> None:
        if session != self._session_id:
            return
        self.chat.add_message("error", f"Não consegui responder: {exc}")
        self.mascot_bubble_lbl.configure(text=f"⚠ Erro: {exc}")
        self._finish_turn()

    def _finish_turn(self) -> None:
        self._busy = False
        self.stt.paused = False
        self._set_input_enabled(True)
        self._update_idle_or_listening_state()
        if not self._mascot_mode:
            self.input.focus_set()

    def _set_input_enabled(self, enabled: bool) -> None:
        self.send_button.configure(
            state="normal" if enabled else "disabled",
            text="Enviar" if enabled else "...",
        )
        self.mascot_send_btn.configure(state="normal" if enabled else "disabled")

    def _on_close(self) -> None:
        self.tts.stop()
        self.mic.hard_mute()  # garante liberação de qualquer dispositivo ao sair
        self.avatar.disconnect()
        self.router.bridge.disconnect()
        self.destroy()
