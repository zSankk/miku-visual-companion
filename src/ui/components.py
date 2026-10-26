"""Componentes visuais reutilizáveis: painel de status, chat e privacidade."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from src.avatar.live2d_widget import (
    MODELS_ROOT_DIR,
    AvatarModelInfo,
    Live2DAvatarController,
    import_live2d_model,
    scan_available_models,
)
from src.core.state import AgentState, Mode
from src.ui import theme
from src.voice.mic_controller import AudioInputDevice, MicController, list_input_devices
from src.voice.stt import AVAILABLE_WHISPER_MODELS, SpeechToText, VoiceSettings
from src.voice.tts import (
    AVAILABLE_MIKU_MODELS,
    AVAILABLE_PT_VOICES,
    AVAILABLE_TTS_PROVIDERS,
    TextToSpeech,
)


# =============================================================================
# Painel de Status
# =============================================================================
class _StatusCard(ctk.CTkFrame):
    def __init__(self, master, caption: str) -> None:
        super().__init__(master, fg_color=theme.BG_CARD, corner_radius=12,
                         border_width=1, border_color=theme.BORDER)
        self.grid_columnconfigure(1, weight=1)

        self.caption = ctk.CTkLabel(
            self, text=caption.upper(), text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        )
        self.caption.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 0))

        self.dot = ctk.CTkLabel(self, text="●", font=ctk.CTkFont(theme.FONT_FAMILY, 16), width=16)
        self.dot.grid(row=1, column=0, sticky="w", padx=(14, 6), pady=(0, 10))

        self.value = ctk.CTkLabel(
            self, text="-", text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 16, "bold"), anchor="w",
        )
        self.value.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=(0, 10))

    def set(self, text: str, color: str) -> None:
        self.value.configure(text=text)
        self.dot.configure(text_color=color)


class StatusPanel(ctk.CTkFrame):
    """Mostra Estado, Humor e Modo ativos."""

    def __init__(self, master) -> None:
        super().__init__(master, fg_color="transparent")
        for col in range(3):
            self.grid_columnconfigure(col, weight=1, uniform="status")

        self.state_card = _StatusCard(self, "Estado")
        self.mood_card = _StatusCard(self, "Humor da Miku")
        self.mode_card = _StatusCard(self, "Modo ativo")
        self.state_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.mood_card.grid(row=0, column=1, sticky="nsew", padx=6)
        self.mode_card.grid(row=0, column=2, sticky="nsew", padx=(6, 0))

        self._state = AgentState.INATIVA
        self._anim_job: str | None = None
        self._anim_step = 0

    # ----------------------------------------------------------------- estado
    def set_state(self, state: AgentState) -> None:
        self._state = state
        if self._anim_job:
            self.after_cancel(self._anim_job)
            self._anim_job = None
        if state in (AgentState.PENSANDO, AgentState.OUVINDO, AgentState.FALANDO):
            self._anim_step = 0
            self._animate()
        else:
            self.state_card.set(state.value, theme.STATE_COLORS[state])

    def _animate(self) -> None:
        dots = "." * (self._anim_step % 4)
        # Pisca o indicador para dar sensação de atividade
        color = theme.STATE_COLORS[self._state] if self._anim_step % 2 == 0 else theme.BORDER
        self.state_card.set(f"{self._state.value}{dots}", color)
        self._anim_step += 1
        self._anim_job = self.after(350, self._animate)

    # ------------------------------------------------------------------ humor
    def set_emotion(self, emotion: str) -> None:
        style = theme.emotion_style(emotion)
        self.mood_card.set(f"{style.icon}  {style.label}", style.color)
        self.mood_card.value.configure(text_color=style.color)

    # ------------------------------------------------------------------- modo
    def set_mode(self, mode: Mode) -> None:
        self.mode_card.set(mode.label, theme.MODE_COLORS[mode])


# =============================================================================
# Chat
# =============================================================================
class MessageBubble(ctk.CTkFrame):
    def __init__(self, master, role: str, text: str, emotion: str | None = None,
                 rin_name: str = "Rin", wraplength: int = 520,
                 memory_saved: str | None = None) -> None:
        is_user = role == "user"
        is_error = role == "error"
        bg = theme.BUBBLE_USER if is_user else theme.BUBBLE_ERROR if is_error else theme.BUBBLE_RIN
        super().__init__(master, fg_color=bg, corner_radius=14)
        self.role = role
        self.full_text = text
        self.memory_saved = memory_saved

        # 🧠 Pill estilo ChatGPT quando a Miku salva uma nova memória
        if memory_saved and not is_user:
            self.memory_pill = ctk.CTkFrame(
                self,
                fg_color="#1e1b4b",
                corner_radius=8,
                border_width=1,
                border_color="#6366f1",
            )
            self.memory_pill.pack(fill="x", padx=14, pady=(8, 2))
            self.memory_lbl = ctk.CTkLabel(
                self.memory_pill,
                text=f"🧠 Memória salva: {memory_saved}",
                text_color="#c7d2fe",
                font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
                anchor="w",
                justify="left",
                wraplength=max(200, wraplength - 28),
                padx=8,
                pady=4,
            )
            self.memory_lbl.pack(fill="x")

        if is_user:
            header_text, header_color = "Você", theme.TEXT_MUTED
        elif is_error:
            header_text, header_color = "Erro", "#f87171"
        else:
            style = theme.emotion_style(emotion)
            header_text, header_color = f"{rin_name}  ·  {style.icon} {style.label.lower()}", style.color

        self.header = ctk.CTkLabel(
            self, text=header_text, text_color=header_color, anchor="w",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
        )
        pady_header = (4, 0) if memory_saved else (8, 0)
        self.header.pack(fill="x", padx=14, pady=pady_header)

        self.body = ctk.CTkLabel(
            self, text=text, text_color=theme.TEXT_PRIMARY, justify="left", anchor="w",
            wraplength=wraplength, font=ctk.CTkFont(theme.FONT_FAMILY, 14),
        )
        self.body.pack(fill="x", padx=14, pady=(2, 10))

        # Clique direito copia a mensagem
        for widget in (self, self.header, self.body):
            widget.bind("<Button-3>", self._copy)

    def set_text(self, text: str) -> None:
        self.body.configure(text=text)

    def set_wraplength(self, value: int) -> None:
        self.body.configure(wraplength=value)
        if hasattr(self, "memory_lbl"):
            self.memory_lbl.configure(wraplength=max(200, value - 28))

    def _copy(self, _event=None) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.full_text)
        original = self.header.cget("text")
        self.header.configure(text="Copiado!")
        self.after(900, lambda: self.header.configure(text=original))


class ChatPanel(ctk.CTkScrollableFrame):
    """Histórico rolável da sessão."""

    def __init__(self, master, rin_name: str = "Rin") -> None:
        super().__init__(master, fg_color=theme.BG_CHAT, corner_radius=14,
                         border_width=1, border_color=theme.BORDER)
        self.rin_name = rin_name
        self.grid_columnconfigure(0, weight=1)
        self._bubbles: list[MessageBubble] = []
        self._row = 0
        self._wrap = 520
        # add="+" preserva o bind interno do CTk que atualiza a área de rolagem
        self.bind("<Configure>", self._on_resize, add="+")
        self._parent_canvas.bind("<MouseWheel>", lambda e: self.after_idle(self.update_idletasks), add="+")

    def _on_resize(self, event) -> None:
        wrap = max(240, int(event.width * 0.68))
        if abs(wrap - self._wrap) > 8:
            self._wrap = wrap
            for bubble in self._bubbles:
                bubble.set_wraplength(wrap)

    def add_message(self, role: str, text: str, emotion: str | None = None,
                    memory_saved: str | None = None) -> MessageBubble:
        bubble = MessageBubble(self, role, text, emotion, self.rin_name, self._wrap, memory_saved=memory_saved)
        sticky = "e" if role == "user" else "w"
        padx = (80, 12) if role == "user" else (12, 80)
        bubble.grid(row=self._row, column=0, sticky=sticky, padx=padx, pady=6)
        self._row += 1
        self._bubbles.append(bubble)
        self.scroll_to_bottom()
        return bubble

    def add_system(self, text: str) -> None:
        label = ctk.CTkLabel(self, text=text, text_color=theme.TEXT_MUTED,
                             font=ctk.CTkFont(theme.FONT_FAMILY, 11, slant="italic"))
        label.grid(row=self._row, column=0, pady=(10, 4))
        self._row += 1
        self.scroll_to_bottom()

    def clear(self) -> None:
        for child in self.winfo_children():
            child.destroy()
        self._bubbles.clear()
        self._row = 0

    def scroll_to_bottom(self) -> None:
        self.after(10, self._do_scroll)

    def _do_scroll(self) -> None:
        self.update_idletasks()
        try:
            self._parent_canvas.yview_moveto(1.0)
        except AttributeError:  # API interna do CTk pode mudar
            pass


# =============================================================================
# Privacidade e Microfone
# =============================================================================
class PrivacyPanel(ctk.CTkFrame):
    """Botão de Hard Mute em destaque + Seletor de Microfone e Medidor de Voz."""

    def __init__(
        self,
        master,
        on_toggle: Callable[[], None],
        on_device_select: Callable[[int | None], None] | None = None,
        on_refresh_devices: Callable[[], list[AudioInputDevice]] | None = None,
        on_open_settings: Callable[[], None] | None = None,
        on_toggle_tts_mute: Callable[[], None] | None = None,
        on_stop_tts: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color=theme.BG_CARD, corner_radius=14,
                         border_width=1, border_color=theme.BORDER)
        self._on_device_select = on_device_select
        self._on_refresh_devices = on_refresh_devices
        self._on_open_settings = on_open_settings
        self._on_toggle_tts_mute = on_toggle_tts_mute
        self._on_stop_tts = on_stop_tts
        self._label_to_index: dict[str, int | None] = {}

        ctk.CTkLabel(
            self, text="PRIVACIDADE & MICROFONE", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 6))

        self.button = ctk.CTkButton(
            self, height=56, corner_radius=12, command=on_toggle,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13, "bold"),
        )
        self.button.pack(fill="x", padx=14)

        self.caption = ctk.CTkLabel(
            self, font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w", justify="left",
        )
        self.caption.pack(fill="x", padx=14, pady=(6, 4))

        # Barra de nível de áudio (VU Meter)
        self.level_bar = ctk.CTkProgressBar(
            self, height=6, corner_radius=3,
            fg_color=theme.BG_SIDEBAR, progress_color=theme.MIC_ON,
        )
        self.level_bar.set(0.0)
        self.level_bar.pack(fill="x", padx=14, pady=(0, 8))

        # Seletor de Dispositivo de Entrada
        dev_header = ctk.CTkFrame(self, fg_color="transparent")
        dev_header.pack(fill="x", padx=14, pady=(2, 2))
        ctk.CTkLabel(
            dev_header, text="Dispositivo de Entrada:", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11), anchor="w",
        ).pack(side="left")

        self.refresh_btn = ctk.CTkButton(
            dev_header, text="↻", width=24, height=20, corner_radius=6,
            fg_color="transparent", hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self.refresh_devices,
        )
        self.refresh_btn.pack(side="right")

        self.device_menu = ctk.CTkOptionMenu(
            self,
            values=["Padrão do Windows"],
            command=self._handle_device_choice,
            fg_color=theme.BG_SIDEBAR,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            dropdown_fg_color=theme.BG_CARD,
            dropdown_hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            height=28,
            corner_radius=8,
            dynamic_resizing=False,
        )
        self.device_menu.pack(fill="x", padx=14, pady=(0, 8))

        # --- Controles rápidos da Voz da Miku (Mutar Voz + Parar Fala) ---
        ctk.CTkLabel(
            self, text="VOZ DA MIKU (VOCALOID / ANIME)", text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(2, 4))

        tts_row = ctk.CTkFrame(self, fg_color="transparent")
        tts_row.pack(fill="x", padx=14, pady=(0, 6))
        tts_row.grid_columnconfigure(0, weight=1)
        tts_row.grid_columnconfigure(1, weight=1)

        self.tts_mute_btn = ctk.CTkButton(
            tts_row,
            text="🔊 Voz Ativa",
            height=30,
            corner_radius=8,
            fg_color=theme.MIC_ON,
            hover_color=theme.MIC_ON_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._handle_toggle_tts_mute,
        )
        self.tts_mute_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.tts_stop_btn = ctk.CTkButton(
            tts_row,
            text="⏹ Parar Fala",
            height=30,
            corner_radius=8,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.MIC_OFF_HOVER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._handle_stop_tts,
        )
        self.tts_stop_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.settings_btn = ctk.CTkButton(
            self,
            text="⚙  Configurar Microfone & Voz",
            height=30,
            corner_radius=8,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            border_width=1,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._handle_open_settings,
        )
        self.settings_btn.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(
            self, text="Atalho: Ctrl+M · Fale quando estiver verde",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10), anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

    def set_devices(self, devices: list[AudioInputDevice], selected_index: int | None = None) -> None:
        self._label_to_index.clear()
        labels: list[str] = []
        selected_label: str | None = None

        for dev in devices:
            short = dev.label if len(dev.label) <= 34 else dev.label[:31] + "..."
            label = short
            counter = 2
            while label in self._label_to_index:
                label = f"{short} ({counter})"
                counter += 1
            self._label_to_index[label] = dev.index
            labels.append(label)
            if dev.index == selected_index:
                selected_label = label

        if not labels:
            labels = ["Padrão do Windows"]
            self._label_to_index["Padrão do Windows"] = None

        self.device_menu.configure(values=labels)
        self.device_menu.set(selected_label or labels[0])

    def refresh_devices(self) -> None:
        if self._on_refresh_devices:
            devices = self._on_refresh_devices()
            self.set_devices(devices)

    def _handle_device_choice(self, label: str) -> None:
        if self._on_device_select and label in self._label_to_index:
            self._on_device_select(self._label_to_index[label])

    def _handle_open_settings(self) -> None:
        if self._on_open_settings:
            self._on_open_settings()

    def _handle_toggle_tts_mute(self) -> None:
        if self._on_toggle_tts_mute:
            self._on_toggle_tts_mute()

    def _handle_stop_tts(self) -> None:
        if self._on_stop_tts:
            self._on_stop_tts()

    def set_tts_enabled(self, enabled: bool) -> None:
        if enabled:
            self.tts_mute_btn.configure(
                text="🔊 Voz Ativa",
                fg_color=theme.MIC_ON,
                hover_color=theme.MIC_ON_HOVER,
            )
        else:
            self.tts_mute_btn.configure(
                text="🔇 Voz Mutada",
                fg_color=theme.MIC_OFF,
                hover_color=theme.MIC_OFF_HOVER,
            )

    def set_tts_speaking(self, speaking: bool) -> None:
        if speaking:
            self.tts_stop_btn.configure(
                fg_color=theme.MIC_OFF,
                hover_color=theme.MIC_OFF_HOVER,
                text="⏹ Parar Fala!",
            )
        else:
            self.tts_stop_btn.configure(
                fg_color=theme.BG_SIDEBAR,
                hover_color=theme.MIC_OFF_HOVER,
                text="⏹ Parar Fala",
            )

    def set_level(self, level: float) -> None:
        self.level_bar.set(max(0.0, min(1.0, level)))

    def set_muted(self, muted: bool) -> None:
        if muted:
            self.button.configure(
                text="■  Microfone Desativado\n(Hard Mute)",
                fg_color=theme.MIC_OFF, hover_color=theme.MIC_OFF_HOVER,
            )
            self.caption.configure(
                text="● Fisicamente desativado (clique p/ falar)",
                text_color=theme.MIC_OFF,
            )
            self.level_bar.set(0.0)
        else:
            self.button.configure(
                text="●  Mutar Microfone\n(Hard Mute)",
                fg_color=theme.MIC_ON, hover_color=theme.MIC_ON_HOVER,
            )
            self.caption.configure(
                text="● Microfone liberado · Ouvindo você!",
                text_color="#4ade80",
            )


# =============================================================================
# Janela de Configuração e Teste de Microfone, Modelo STT & Voz da Rin (TTS)
# =============================================================================
class VoiceSettingsDialog(ctk.CTkToplevel):
    """Modal rolável e redimensionável para configurar microfone, STT local e voz da Rin."""

    def __init__(
        self,
        master,
        mic: MicController,
        stt: SpeechToText,
        tts: TextToSpeech,
        voice_settings: VoiceSettings,
        on_settings_changed: Callable[[], None] | None = None,
        dispatch_ui: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color=theme.BG_APP)
        self.mic = mic
        self.stt = stt
        self.tts = tts
        self.voice_settings = voice_settings
        self.on_settings_changed = on_settings_changed
        self._dispatch_ui = dispatch_ui or (lambda fn: self.after(0, fn))
        self._label_to_index: dict[str, int | None] = {}
        self._voice_label_to_id: dict[str, str] = dict(AVAILABLE_PT_VOICES)
        self._voice_id_to_label: dict[str, str] = {v: k for k, v in AVAILABLE_PT_VOICES.items()}
        self._provider_label_to_id: dict[str, str] = dict(AVAILABLE_TTS_PROVIDERS)
        self._provider_id_to_label: dict[str, str] = {v: k for k, v in AVAILABLE_TTS_PROVIDERS.items()}
        self._miku_label_to_id: dict[str, str] = dict(AVAILABLE_MIKU_MODELS)
        self._miku_id_to_label: dict[str, str] = {v: k for k, v in AVAILABLE_MIKU_MODELS.items()}
        self._testing_stt = False

        self.title("Configurar & Testar Microfone e Voz da Miku")
        self.geometry("600x700")
        self.minsize(520, 480)
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _ui(self, fn: Callable[[], None]) -> None:
        """Executa `fn` com segurança na thread principal da UI."""
        def _safe() -> None:
            if self.winfo_exists():
                fn()

        self._dispatch_ui(_safe)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        container = ctk.CTkScrollableFrame(
            self, fg_color="transparent", corner_radius=0,
        )
        container.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            container,
            text="Configuração de Microfone, STT & Voz da Miku",
            text_color=theme.ACCENT,
            font=ctk.CTkFont(theme.FONT_FAMILY, 20, "bold"),
            anchor="w",
        ).pack(fill="x", padx=6, pady=(0, 2))
        ctk.CTkLabel(
            container,
            text="Role para baixo se precisar · Você também pode redimensionar esta janela.",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
        ).pack(fill="x", padx=6, pady=(0, 10))

        # ------------------------------------------------- 1. Dispositivo + Escuta
        dev_card = ctk.CTkFrame(
            container, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        dev_card.pack(fill="x", padx=6, pady=(0, 10))

        ctk.CTkLabel(
            dev_card, text="1. DISPOSITIVO E TESTE DE ESCUTA (LOOPBACK)",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        row_dev = ctk.CTkFrame(dev_card, fg_color="transparent")
        row_dev.pack(fill="x", padx=14, pady=(0, 8))
        row_dev.grid_columnconfigure(0, weight=1)

        self.dev_menu = ctk.CTkOptionMenu(
            row_dev,
            values=["Padrão do Windows"],
            command=self._on_device_chosen,
            fg_color=theme.BG_SIDEBAR,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            dropdown_fg_color=theme.BG_CARD,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=32,
        )
        self.dev_menu.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        ctk.CTkButton(
            row_dev, text="↻ Atualizar", width=90, height=32,
            fg_color=theme.BG_SIDEBAR, hover_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._populate_devices,
        ).grid(row=0, column=1)

        self.test_bar = ctk.CTkProgressBar(
            dev_card, height=8, corner_radius=4,
            fg_color=theme.BG_SIDEBAR, progress_color=theme.MIC_ON,
        )
        self.test_bar.set(0.0)
        self.test_bar.pack(fill="x", padx=14, pady=(0, 8))

        self.loopback_btn = ctk.CTkButton(
            dev_card,
            text="🎧  Testar Escutando Meu Microfone (Loopback)",
            height=36,
            corner_radius=8,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._toggle_loopback,
        )
        self.loopback_btn.pack(fill="x", padx=14, pady=(0, 12))

        # ------------------------------------------------- 2. Tempo de atraso & Sensibilidade
        timing_card = ctk.CTkFrame(
            container, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        timing_card.pack(fill="x", padx=6, pady=(0, 10))

        ctk.CTkLabel(
            timing_card, text="2. TEMPO DE ATRASO PÓS-FALA & SENSIBILIDADE",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        self.delay_label = ctk.CTkLabel(
            timing_card,
            text=f"Atraso para começar a pensar após você parar de falar: {self.stt.silence_duration_s:.1f}s",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.delay_label.pack(fill="x", padx=14)
        ctk.CTkLabel(
            timing_card,
            text="Menor (0.4s) = responde mais rápido · Maior (1.5s–2.5s) = espera você fazer pausas longas",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 4))

        self.delay_slider = ctk.CTkSlider(
            timing_card,
            from_=0.3,
            to=3.0,
            number_of_steps=27,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_delay_changed,
        )
        self.delay_slider.set(self.stt.silence_duration_s)
        self.delay_slider.pack(fill="x", padx=14, pady=(0, 10))

        self.sens_label = ctk.CTkLabel(
            timing_card,
            text=f"Limiar de volume da voz (Sensibilidade): {self.stt.energy_threshold:.3f}",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.sens_label.pack(fill="x", padx=14)
        ctk.CTkLabel(
            timing_card,
            text="Menor (0.005) = capta voz baixa · Maior (0.035) = ignora barulho de ventilador/teclado",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 4))

        self.sens_slider = ctk.CTkSlider(
            timing_card,
            from_=0.003,
            to=0.060,
            number_of_steps=57,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_sens_changed,
        )
        self.sens_slider.set(self.stt.energy_threshold)
        self.sens_slider.pack(fill="x", padx=14, pady=(0, 12))

        # ------------------------------------------------- 3. Modelo de Voz & Teste de Transcrição
        model_card = ctk.CTkFrame(
            container, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        model_card.pack(fill="x", padx=6, pady=(0, 10))

        ctk.CTkLabel(
            model_card, text="3. MODELO FASTER-WHISPER (100% LOCAL) & TESTE DE VOZ",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        row_model = ctk.CTkFrame(model_card, fg_color="transparent")
        row_model.pack(fill="x", padx=14, pady=(0, 8))
        row_model.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_model, text="Modelo Local:", text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
        ).grid(row=0, column=0, padx=(0, 10))

        self.model_seg = ctk.CTkSegmentedButton(
            row_model,
            values=list(AVAILABLE_WHISPER_MODELS),
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            fg_color=theme.BG_SIDEBAR,
            unselected_color=theme.BG_SIDEBAR,
            command=self._on_model_changed,
        )
        self.model_seg.set(self.stt.model_size)
        self.model_seg.grid(row=0, column=1, sticky="ew")

        self.test_stt_btn = ctk.CTkButton(
            model_card,
            text="🎙️  Gravar 3.5s e Testar Modelo de Voz Agora",
            height=38,
            corner_radius=8,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._run_stt_test,
        )
        self.test_stt_btn.pack(fill="x", padx=14, pady=(2, 8))

        result_box = ctk.CTkFrame(
            model_card, fg_color=theme.BG_SIDEBAR, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
        )
        result_box.pack(fill="x", padx=14, pady=(0, 12))

        self.test_result = ctk.CTkLabel(
            result_box,
            text="Resultado do teste aparecerá aqui (não envia para o chat).",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            wraplength=490,
            justify="left",
            anchor="w",
        )
        self.test_result.pack(fill="x", padx=12, pady=10)

        # ------------------------------------------------- 4. Voz da Miku (John6666/mikuTTS + Fallback Edge-TTS)
        tts_card = ctk.CTkFrame(
            container, fg_color=theme.BG_CARD, corner_radius=12,
            border_width=1, border_color=theme.BORDER,
        )
        tts_card.pack(fill="x", padx=6, pady=(0, 10))

        ctk.CTkLabel(
            tts_card, text="4. VOZ DA MIKU (JOHN6666/MIKUTTS + FALLBACK AUTOMÁTICO EDGE-TTS)",
            text_color=theme.TEXT_MUTED, font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"), anchor="w",
        ).pack(fill="x", padx=14, pady=(10, 6))

        self.tts_switch = ctk.CTkSwitch(
            tts_card,
            text="Ativar Voz da Miku (fala todas as respostas automaticamente)",
            progress_color=theme.ACCENT,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._on_tts_toggled,
        )
        if self.tts.enabled:
            self.tts_switch.select()
        else:
            self.tts_switch.deselect()
        self.tts_switch.pack(fill="x", padx=14, pady=(0, 8))

        # Seletor de Provedor (miku_hf vs edge_tts)
        row_provider = ctk.CTkFrame(tts_card, fg_color="transparent")
        row_provider.pack(fill="x", padx=14, pady=(0, 8))
        row_provider.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_provider, text="Provedor TTS:", text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
        ).grid(row=0, column=0, padx=(0, 10))

        self.provider_menu = ctk.CTkOptionMenu(
            row_provider,
            values=list(AVAILABLE_TTS_PROVIDERS.keys()),
            command=self._on_tts_provider_chosen,
            fg_color=theme.BG_SIDEBAR,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            dropdown_fg_color=theme.BG_CARD,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=32,
        )
        current_prov_label = self._provider_id_to_label.get(
            self.tts.tts_provider, next(iter(AVAILABLE_TTS_PROVIDERS.keys()))
        )
        self.provider_menu.set(current_prov_label)
        self.provider_menu.grid(row=0, column=1, sticky="ew")

        # Seletor de Modelo da Miku (John6666/mikuTTS)
        row_miku = ctk.CTkFrame(tts_card, fg_color="transparent")
        row_miku.pack(fill="x", padx=14, pady=(0, 8))
        row_miku.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_miku, text="Modelo Miku RVC:", text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
        ).grid(row=0, column=0, padx=(0, 10))

        self.miku_menu = ctk.CTkOptionMenu(
            row_miku,
            values=list(AVAILABLE_MIKU_MODELS.keys()),
            command=self._on_miku_model_chosen,
            fg_color=theme.BG_SIDEBAR,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            dropdown_fg_color=theme.BG_CARD,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=32,
        )
        current_miku_label = self._miku_id_to_label.get(
            self.tts.miku_model, next(iter(AVAILABLE_MIKU_MODELS.keys()))
        )
        self.miku_menu.set(current_miku_label)
        self.miku_menu.grid(row=0, column=1, sticky="ew")

        self.phonetic_switch = ctk.CTkSwitch(
            tts_card,
            text="Adaptação Fonética PT-BR → Romaji/Vocaloid (sotaque natural da Miku)",
            progress_color=theme.ACCENT,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._on_phonetic_toggled,
        )
        if self.tts.miku_phonetic_ptbr:
            self.phonetic_switch.select()
        else:
            self.phonetic_switch.deselect()
        self.phonetic_switch.pack(fill="x", padx=14, pady=(0, 10))

        # Slider de Timeout do mikuTTS (Fallback de segurança)
        self.timeout_label = ctk.CTkLabel(
            tts_card,
            text=f"Timeout do mikuTTS para Fallback Automático: {self.tts.miku_timeout_s:.0f}s",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.timeout_label.pack(fill="x", padx=14)
        ctk.CTkLabel(
            tts_card,
            text="Se a Space do Hugging Face demorar ou estiver Sleeping, usa Edge-TTS (+15Hz) automaticamente.",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 4))

        self.timeout_slider = ctk.CTkSlider(
            tts_card,
            from_=10.0,
            to=60.0,
            number_of_steps=50,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_miku_timeout_changed,
        )
        self.timeout_slider.set(self.tts.miku_timeout_s)
        self.timeout_slider.pack(fill="x", padx=14, pady=(0, 10))

        # Timbre de Fallback / Edge-TTS Puro
        row_voice = ctk.CTkFrame(tts_card, fg_color="transparent")
        row_voice.pack(fill="x", padx=14, pady=(0, 8))
        row_voice.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            row_voice, text="Voz Edge-TTS / Fallback:", text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
        ).grid(row=0, column=0, padx=(0, 10))

        self.voice_menu = ctk.CTkOptionMenu(
            row_voice,
            values=list(AVAILABLE_PT_VOICES.keys()),
            command=self._on_tts_voice_chosen,
            fg_color=theme.BG_SIDEBAR,
            button_color=theme.BORDER,
            button_hover_color=theme.ACCENT,
            dropdown_fg_color=theme.BG_CARD,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=32,
        )
        current_label = self._voice_id_to_label.get(
            self.tts.voice, next(iter(AVAILABLE_PT_VOICES.keys()))
        )
        self.voice_menu.set(current_label)
        self.voice_menu.grid(row=0, column=1, sticky="ew")

        # Slider de Pitch em Hz (Edge-TTS puro, sem Pedalboard)
        self.pitch_label = ctk.CTkLabel(
            tts_card,
            text=f"Pitch do Edge-TTS Puro (sem Pedalboard): {self.tts.pitch_hz:+d}Hz",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.pitch_label.pack(fill="x", padx=14)
        ctk.CTkLabel(
            tts_card,
            text="Padrão recomendado para Fallback: +15Hz (sem efeito de esquilo)",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 4))

        self.pitch_slider = ctk.CTkSlider(
            tts_card,
            from_=-20,
            to=40,
            number_of_steps=60,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_tts_pitch_changed,
        )
        self.pitch_slider.set(self.tts.pitch_hz)
        self.pitch_slider.pack(fill="x", padx=14, pady=(0, 10))

        # Slider de Velocidade (tts_rate)
        self.rate_label = ctk.CTkLabel(
            tts_card,
            text=f"Velocidade da Fala (tts_rate): {self.tts.base_rate_pct:+d}%",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.rate_label.pack(fill="x", padx=14)

        self.rate_slider = ctk.CTkSlider(
            tts_card,
            from_=-25,
            to=40,
            number_of_steps=65,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_tts_rate_changed,
        )
        self.rate_slider.set(self.tts.base_rate_pct)
        self.rate_slider.pack(fill="x", padx=14, pady=(4, 10))

        # Slider de Volume
        self.vol_label = ctk.CTkLabel(
            tts_card,
            text=f"Volume da Voz da Miku: {int(round(self.tts.volume * 100))}%",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.vol_label.pack(fill="x", padx=14)

        self.vol_slider = ctk.CTkSlider(
            tts_card,
            from_=0.1,
            to=1.0,
            number_of_steps=18,
            button_color=theme.ACCENT,
            button_hover_color=theme.ACCENT_HOVER,
            progress_color=theme.ACCENT,
            command=self._on_tts_volume_changed,
        )
        self.vol_slider.set(self.tts.volume)
        self.vol_slider.pack(fill="x", padx=14, pady=(4, 10))

        row_tts_btns = ctk.CTkFrame(tts_card, fg_color="transparent")
        row_tts_btns.pack(fill="x", padx=14, pady=(0, 12))
        row_tts_btns.grid_columnconfigure(0, weight=1)
        row_tts_btns.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            row_tts_btns,
            text="🔊  Testar Voz da Miku (mikuTTS / Fallback)",
            height=36,
            corner_radius=8,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._test_tts_voice,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))

        ctk.CTkButton(
            row_tts_btns,
            text="⏹  Parar Fala",
            height=36,
            corner_radius=8,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.MIC_OFF_HOVER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self.tts.stop,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Rodapé fixo com botão Salvar e Fechar
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=1, column=0, sticky="ew", padx=18, pady=(4, 14))
        ctk.CTkButton(
            footer,
            text="Salvar e Fechar",
            height=40,
            corner_radius=10,
            fg_color=theme.MIC_ON,
            hover_color=theme.MIC_ON_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13, "bold"),
            command=self._on_close,
        ).pack(fill="x")

        self._populate_devices()

    def _populate_devices(self) -> None:
        devices = list_input_devices()
        self._label_to_index.clear()
        labels: list[str] = []
        selected_label: str | None = None
        for dev in devices:
            label = dev.label
            counter = 2
            while label in self._label_to_index:
                label = f"{dev.label} ({counter})"
                counter += 1
            self._label_to_index[label] = dev.index
            labels.append(label)
            if dev.index == self.mic.device_index:
                selected_label = label
        self.dev_menu.configure(values=labels)
        self.dev_menu.set(selected_label or labels[0])

    def _on_device_chosen(self, label: str) -> None:
        idx = self._label_to_index.get(label)
        self.mic.set_device(idx)
        self.voice_settings.device_index = idx
        self.voice_settings.save()
        if self.on_settings_changed:
            self.on_settings_changed()

    def _on_delay_changed(self, value: float) -> None:
        val = round(float(value), 1)
        self.delay_label.configure(
            text=f"Atraso para começar a pensar após você parar de falar: {val:.1f}s"
        )
        self.stt.set_silence_duration(val)
        self.voice_settings.silence_duration_s = val
        self.voice_settings.save()

    def _on_sens_changed(self, value: float) -> None:
        val = round(float(value), 3)
        self.sens_label.configure(text=f"Limiar de volume da voz (Sensibilidade): {val:.3f}")
        self.stt.set_energy_threshold(val)
        self.voice_settings.energy_threshold = val
        self.voice_settings.save()

    def _on_model_changed(self, model_name: str) -> None:
        self.test_result.configure(
            text=f"⏳ Carregando modelo '{model_name}' em background...",
            text_color="#facc15",
        )
        self.voice_settings.whisper_model = model_name
        self.voice_settings.save()
        self.stt.set_model_size(model_name, preload=False)
        self.stt.preload_model_async(
            on_ready=lambda m: self._ui(
                lambda: self.test_result.configure(
                    text=f"✔ Modelo '{m}' pronto para uso 100% local!",
                    text_color="#4ade80",
                )
            )
        )

    def _on_tts_toggled(self) -> None:
        enabled = bool(self.tts_switch.get())
        self.tts.enabled = enabled
        self.voice_settings.tts_enabled = enabled
        self.voice_settings.save()
        if not enabled:
            self.tts.stop()
        if self.on_settings_changed:
            self.on_settings_changed()

    def _on_tts_provider_chosen(self, label: str) -> None:
        prov_id = self._provider_label_to_id.get(label, "miku_hf")
        self.tts.tts_provider = prov_id
        self.voice_settings.tts_provider = prov_id
        self.voice_settings.save()

    def _on_miku_model_chosen(self, label: str) -> None:
        model_id = self._miku_label_to_id.get(label, "1a_miku_default_rvc_(aple)")
        self.tts.miku_model = model_id
        self.voice_settings.miku_model = model_id
        self.voice_settings.save()

    def _on_phonetic_toggled(self) -> None:
        phonetic = bool(self.phonetic_switch.get())
        self.tts.miku_phonetic_ptbr = phonetic
        self.voice_settings.miku_phonetic_ptbr = phonetic
        self.voice_settings.save()

    def _on_miku_timeout_changed(self, value: float) -> None:
        timeout_s = round(float(value), 0)
        self.timeout_label.configure(
            text=f"Timeout do mikuTTS para Fallback Automático: {timeout_s:.0f}s"
        )
        self.tts.miku_timeout_s = timeout_s
        self.voice_settings.miku_timeout_s = timeout_s
        self.voice_settings.save()

    def _on_tts_voice_chosen(self, label: str) -> None:
        voice_id = self._voice_label_to_id.get(label, "pt-BR-LeticiaNeural")
        self.tts.voice = voice_id
        self.voice_settings.tts_voice = voice_id
        self.voice_settings.save()

    def _on_tts_pitch_changed(self, value: float) -> None:
        pitch_hz = int(round(float(value)))
        self.pitch_label.configure(
            text=f"Pitch do Edge-TTS Puro (sem Pedalboard): {pitch_hz:+d}Hz"
        )
        self.tts.pitch_hz = pitch_hz
        self.voice_settings.tts_pitch_hz = pitch_hz
        self.voice_settings.save()

    def _on_tts_rate_changed(self, value: float) -> None:
        rate_pct = int(round(float(value)))
        self.rate_label.configure(text=f"Velocidade da Fala (tts_rate): {rate_pct:+d}%")
        self.tts.base_rate_pct = rate_pct
        self.voice_settings.tts_rate_pct = rate_pct
        self.voice_settings.save()

    def _on_tts_volume_changed(self, value: float) -> None:
        vol = round(float(value), 2)
        self.vol_label.configure(text=f"Volume da Voz da Miku: {int(round(vol * 100))}%")
        self.tts.volume = vol
        self.voice_settings.tts_volume = vol
        self.voice_settings.save()

    def _test_tts_voice(self) -> None:
        was_enabled = self.tts.enabled
        self.tts.enabled = True
        self.tts.speak(
            "Oi! Eu sou a Miku! Agora minha voz tem efeito Vocaloid estilo anime. O que você achou?",
            emotion="feliz",
            on_done=lambda: setattr(self.tts, "enabled", was_enabled),
        )

    def _toggle_loopback(self) -> None:
        if self.stt.is_loopback_active:
            self.stt.stop_loopback()
            self.test_bar.set(0.0)
            self.loopback_btn.configure(
                text="🎧  Testar Escutando Meu Microfone (Loopback)",
                fg_color=theme.BG_SIDEBAR,
            )
        else:
            try:
                self.stt.start_loopback(
                    on_level=lambda lvl: self._ui(lambda l=lvl: self.test_bar.set(l))
                )
                self.loopback_btn.configure(
                    text="⏹  Parar Escuta do Microfone (Ouvindo em Tempo Real...)",
                    fg_color=theme.MIC_OFF,
                )
            except Exception as exc:
                self.test_result.configure(
                    text=f"Erro ao abrir microfone para escuta: {exc}",
                    text_color="#f87171",
                )

    def _run_stt_test(self) -> None:
        if self._testing_stt:
            return
        if self.stt.is_loopback_active:
            self._toggle_loopback()

        self._testing_stt = True
        self.test_stt_btn.configure(state="disabled", text="🔴 Gravando 3.5s... Fale agora!")
        self.test_result.configure(
            text="🔴 Gravando sua voz... Fale uma frase no microfone selecionado!",
            text_color="#facc15",
        )

        def _worker() -> None:
            try:
                text, elapsed = self.stt.record_and_transcribe_test(
                    duration_s=3.5,
                    on_level=lambda lvl: self._ui(lambda l=lvl: self.test_bar.set(l)),
                    on_status=lambda st: self._ui(
                        lambda s=st: (
                            self.test_stt_btn.configure(text=s),
                            self.test_result.configure(text=s, text_color="#facc15"),
                        )
                    ),
                )
                msg = (
                    f"✔ Reconhecido em {elapsed:.2f}s ({self.stt.model_size}):\n\"{text}\""
                    if text
                    else f"⚠ Nenhuma fala detectada ({elapsed:.2f}s). Fale mais perto ou diminua o limiar de volume."
                )
                color = "#4ade80" if text else "#facc15"
            except Exception as exc:
                msg = f"✖ Erro no teste: {exc}"
                color = "#f87171"

            def _done() -> None:
                self._testing_stt = False
                self.test_bar.set(0.0)
                self.test_stt_btn.configure(
                    state="normal",
                    text="🎙️  Gravar 3.5s e Testar Modelo de Voz Agora",
                )
                self.test_result.configure(text=msg, text_color=color)

            self._ui(_done)

        threading.Thread(target=_worker, daemon=True, name="rin-stt-test").start()

    def _on_close(self) -> None:
        self.stt.stop_loopback()
        if not self.mic.is_muted and not self.stt.listening:
            try:
                self.stt.start()
            except Exception:
                pass
        if self.on_settings_changed:
            self.on_settings_changed()
        self.grab_release()
        self.destroy()


# =============================================================================
# Aba "🎭 Modelos" (Estúdio de Modelos & Emotes Live2D)
# =============================================================================
class ModelsStudioPanel(ctk.CTkScrollableFrame):
    """Aba dedicada '🎭 Modelos' para gerenciar modelos Live2D, ajustes visuais e emotes."""

    def __init__(
        self,
        master,
        avatar: Live2DAvatarController,
        on_test_sing_speak: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(
            master,
            fg_color=theme.BG_CHAT,
            corner_radius=14,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.avatar = avatar
        self._on_test_sing_speak = on_test_sing_speak
        self._detail_labels: list[ctk.CTkLabel] = []
        self.grid_columnconfigure(0, weight=1)
        self.bind("<Configure>", self._on_resize, add="+")
        self._parent_canvas.bind("<MouseWheel>", lambda e: self.after_idle(self.update_idletasks), add="+")

        # ----------------------------------------------------- Cabeçalho e Importação
        header_card = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=12, border_width=1, border_color=theme.BORDER
        )
        header_card.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        header_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header_card,
            text="🎭 Estúdio de Modelos & Emotes Live2D",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))

        self.header_desc = ctk.CTkLabel(
            header_card,
            text=(
                "Selecione qualquer modelo em assets/models/ (padrão: Hatsune Miku · Projeto Sekai) "
                "ou importe novos modelos .zip / pastas."
            ),
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
            justify="left",
            wraplength=480,
        )
        self.header_desc.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        btn_row = ctk.CTkFrame(header_card, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        btn_row.grid_columnconfigure(0, weight=1)
        btn_row.grid_columnconfigure(1, weight=1)

        ctk.CTkButton(
            btn_row,
            text="📦 Importar Modelo (.zip)",
            height=34,
            corner_radius=9,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._import_zip_or_file,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))

        ctk.CTkButton(
            btn_row,
            text="📁 Importar Pasta",
            height=34,
            corner_radius=9,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._import_folder,
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0), pady=(0, 4))

        ctk.CTkButton(
            btn_row,
            text="📂 Abrir Pasta assets/models",
            height=34,
            corner_radius=9,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._open_models_folder,
        ).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(4, 0))

        ctk.CTkButton(
            btn_row,
            text="↻ Atualizar Galeria",
            height=34,
            corner_radius=9,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            border_width=1,
            border_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self.refresh_models_gallery,
        ).grid(row=1, column=1, sticky="ew", padx=(4, 0), pady=(4, 0))

        self.feedback_lbl = ctk.CTkLabel(
            header_card,
            text="",
            text_color="#4ade80",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
        )
        self.feedback_lbl.grid(row=3, column=0, sticky="w", padx=14, pady=(0, 8))

        # ----------------------------------------------------- Galeria de Modelos
        gallery_card = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=12, border_width=1, border_color=theme.BORDER
        )
        gallery_card.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        gallery_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            gallery_card,
            text="MODELOS DISPONÍVEIS EM ASSETS/MODELS/",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        self.models_list_frame = ctk.CTkFrame(gallery_card, fg_color=theme.BG_CARD)
        self.models_list_frame.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.models_list_frame.grid_columnconfigure(0, weight=1)

        # ----------------------------------------------------- Sliders de Ajuste Visual & LipSync
        sliders_card = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=12, border_width=1, border_color=theme.BORDER
        )
        sliders_card.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        sliders_card.grid_columnconfigure(0, weight=1)

        sliders_top = ctk.CTkFrame(sliders_card, fg_color="transparent")
        sliders_top.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        sliders_top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            sliders_top,
            text="AJUSTES DE ENQUADRAMENTO & LIPSYNC EM TEMPO REAL",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkButton(
            sliders_top,
            text="↺ Resetar Enquadramento",
            width=145,
            height=26,
            corner_radius=7,
            fg_color=theme.BG_SIDEBAR,
            hover_color=theme.BORDER,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=self._reset_transform,
        ).grid(row=0, column=1, sticky="e")

        # 1. Zoom (Escala)
        self.zoom_val_lbl = self._add_slider_row(
            sliders_card,
            row=1,
            title="Zoom (Escala do Modelo):",
            value_text=f"{self.avatar.settings.zoom:.2f}x",
        )
        self.zoom_slider = ctk.CTkSlider(
            sliders_card,
            from_=0.40,
            to=2.80,
            number_of_steps=80,
            progress_color=theme.ACCENT,
            command=self._on_zoom_changed,
        )
        self.zoom_slider.set(self.avatar.settings.zoom)
        self.zoom_slider.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))

        # 2. Posição X
        self.pos_x_lbl = self._add_slider_row(
            sliders_card,
            row=3,
            title="Posição Horizontal (Eixo X):",
            value_text=f"{self.avatar.settings.offset_x:+.0f} px",
        )
        self.pos_x_slider = ctk.CTkSlider(
            sliders_card,
            from_=-400.0,
            to=400.0,
            number_of_steps=80,
            progress_color=theme.ACCENT,
            command=self._on_pos_x_changed,
        )
        self.pos_x_slider.set(self.avatar.settings.offset_x)
        self.pos_x_slider.grid(row=4, column=0, sticky="ew", padx=14, pady=(0, 8))

        # 3. Posição Y
        self.pos_y_lbl = self._add_slider_row(
            sliders_card,
            row=5,
            title="Posição Vertical (Eixo Y):",
            value_text=f"{self.avatar.settings.offset_y:+.0f} px",
        )
        self.pos_y_slider = ctk.CTkSlider(
            sliders_card,
            from_=-500.0,
            to=500.0,
            number_of_steps=100,
            progress_color=theme.ACCENT,
            command=self._on_pos_y_changed,
        )
        self.pos_y_slider.set(self.avatar.settings.offset_y)
        self.pos_y_slider.grid(row=6, column=0, sticky="ew", padx=14, pady=(0, 8))

        # 4. Sensibilidade do LipSync
        self.lipsync_lbl = self._add_slider_row(
            sliders_card,
            row=7,
            title="Sensibilidade da Boca (LipSync 60 FPS):",
            value_text=f"{self.avatar.settings.lip_sync_sensitivity:.2f}x",
        )
        self.lipsync_slider = ctk.CTkSlider(
            sliders_card,
            from_=0.30,
            to=2.40,
            number_of_steps=42,
            progress_color=theme.MIC_ON,
            command=self._on_lipsync_changed,
        )
        self.lipsync_slider.set(self.avatar.settings.lip_sync_sensitivity)
        self.lipsync_slider.grid(row=8, column=0, sticky="ew", padx=14, pady=(0, 14))

        # ----------------------------------------------------- Soundboard & Guia de Download
        emote_card = ctk.CTkFrame(
            self, fg_color=theme.BG_CARD, corner_radius=12, border_width=1, border_color=theme.BORDER
        )
        emote_card.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 12))
        emote_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            emote_card,
            text="PAINEL DE TESTE DE EMOTES & ONDE BAIXAR MAIS MODELOS DA MIKU",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 6))

        sb_row = ctk.CTkFrame(emote_card, fg_color="transparent")
        sb_row.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        for col in range(5):
            sb_row.grid_columnconfigure(col, weight=1)

        test_emotes = [
            ("👋 Acenar", lambda: self.avatar.trigger_action("acenar")),
            ("😊 Sorrir", lambda: self.avatar.trigger_action("feliz")),
            ("🤔 Pensar", lambda: self.avatar.trigger_action("pensar")),
            ("💢 Irritada", lambda: self.avatar.trigger_action("bravo")),
            ("🎵 Cantar/Falar", self._trigger_sing_speak),
        ]
        for idx, (label, fn) in enumerate(test_emotes):
            ctk.CTkButton(
                sb_row,
                text=label,
                height=32,
                corner_radius=8,
                fg_color=theme.BG_SIDEBAR,
                hover_color=theme.ACCENT,
                border_width=1,
                border_color=theme.BORDER,
                font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
                command=fn,
            ).grid(row=0, column=idx, sticky="ew", padx=3)

        guide_text = (
            "💡 Onde baixar mais trajes da Hatsune Miku (Project Sekai / Live2D):\n"
            "• Sekai Viewer (sekai.best/l2d) ou Untitled Sekai Viewer: baixe qualquer traje da Miku (21miku_normal, "
            "21miku_unit, 21miku_night, 21miku_wonder) em .zip e clique em '📂 Importar Novo Modelo Live2D (.zip)'.\n"
            "• Booth.pm / Live2D Official Sample Data / VTube Studio Workshop: qualquer modelo .model3.json ou .model.json "
            "é reconhecido automaticamente!"
        )
        self.guide_lbl = ctk.CTkLabel(
            emote_card,
            text=guide_text,
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            justify="left",
            anchor="w",
            wraplength=480,
        )
        self.guide_lbl.grid(row=2, column=0, sticky="w", padx=14, pady=(0, 12))

        self.refresh_models_gallery()

    def _add_slider_row(self, parent, row: int, title: str, value_text: str) -> ctk.CTkLabel:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=row, column=0, sticky="ew", padx=14, pady=(2, 2))
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            frame,
            text=title,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        val_lbl = ctk.CTkLabel(
            frame,
            text=value_text,
            text_color=theme.ACCENT,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="e",
        )
        val_lbl.grid(row=0, column=1, sticky="e")
        return val_lbl

    def _on_resize(self, event=None) -> None:
        w = max(240, self.winfo_width() - 36)
        if hasattr(self, "header_desc"):
            self.header_desc.configure(wraplength=w)
        if hasattr(self, "guide_lbl"):
            self.guide_lbl.configure(wraplength=w)
        if hasattr(self, "_detail_labels"):
            card_wrap = max(180, w - 190)
            for lbl in self._detail_labels:
                try:
                    lbl.configure(wraplength=card_wrap)
                except Exception:
                    pass

    def refresh_models_gallery(self) -> None:
        if hasattr(self, "_detail_labels"):
            self._detail_labels.clear()
        if hasattr(self, "zoom_slider"):
            self.zoom_slider.set(self.avatar.settings.zoom)
            self.zoom_val_lbl.configure(text=f"{self.avatar.settings.zoom:.2f}x")
        if hasattr(self, "pos_x_slider"):
            self.pos_x_slider.set(self.avatar.settings.offset_x)
            self.pos_x_lbl.configure(text=f"{self.avatar.settings.offset_x:+.0f} px")
        if hasattr(self, "pos_y_slider"):
            self.pos_y_slider.set(self.avatar.settings.offset_y)
            self.pos_y_lbl.configure(text=f"{self.avatar.settings.offset_y:+.0f} px")
        for child in self.models_list_frame.winfo_children():
            child.destroy()

        models = scan_available_models()
        active_rel = self.avatar.model_path.replace("\\", "/").lower()

        if not models:
            ctk.CTkLabel(
                self.models_list_frame,
                text="Nenhum modelo encontrado em assets/models/.",
                text_color=theme.TEXT_MUTED,
            ).grid(row=0, column=0, sticky="w", padx=6, pady=6)
            return

        for idx, info in enumerate(models):
            is_active = info.rel_path.lower() in active_rel or active_rel.endswith(info.rel_path.lower())
            border_col = theme.ACCENT if is_active else theme.BORDER
            card = ctk.CTkFrame(
                self.models_list_frame,
                fg_color=theme.BG_SIDEBAR,
                corner_radius=10,
                border_width=2 if is_active else 1,
                border_color=border_col,
            )
            card.grid(row=idx, column=0, sticky="ew", pady=4)
            card.grid_columnconfigure(1, weight=1)

            # Badge visual (Ícone Miku / Live2D)
            badge_icon = "🎤" if "miku" in info.folder_name.lower() else "✨"
            badge = ctk.CTkLabel(
                card,
                text=badge_icon,
                width=44,
                height=44,
                corner_radius=10,
                fg_color=theme.BG_CARD,
                font=ctk.CTkFont(theme.FONT_FAMILY, 20),
            )
            badge.grid(row=0, column=0, rowspan=2, padx=10, pady=10)

            ctk.CTkLabel(
                card,
                text=info.name,
                text_color=theme.TEXT_PRIMARY,
                font=ctk.CTkFont(theme.FONT_FAMILY, 13, "bold"),
                anchor="w",
            ).grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(8, 0))

            physics_tag = "Física de Cabelo ✔" if info.has_physics else "Sem física"
            details = (
                f"{info.sdk_label}  ·  {info.motions_count} motions  ·  "
                f"{info.expressions_count} expressões  ·  {physics_tag}\n"
                f"Arquivo: {info.rel_path}"
            )
            det_lbl = ctk.CTkLabel(
                card,
                text=details,
                text_color=theme.TEXT_MUTED,
                font=ctk.CTkFont(theme.FONT_FAMILY, 10),
                justify="left",
                anchor="w",
                wraplength=max(180, int(self.winfo_width() - 200)),
            )
            det_lbl.grid(row=1, column=1, sticky="w", padx=(0, 8), pady=(2, 8))
            self._detail_labels.append(det_lbl)

            btn_text = "✓ Em Uso" if is_active else "Carregar Modelo"
            btn_fg = theme.MIC_ON if is_active else theme.ACCENT
            ctk.CTkButton(
                card,
                text=btn_text,
                width=126,
                height=32,
                corner_radius=8,
                fg_color=btn_fg,
                hover_color=theme.MIC_ON_HOVER if is_active else theme.ACCENT_HOVER,
                font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
                command=lambda rel=info.rel_path, name=info.name: self._select_model(rel, name),
            ).grid(row=0, column=2, rowspan=2, padx=10, pady=10)

    def _select_model(self, rel_path: str, name: str) -> None:
        self.avatar.set_model_path(rel_path, persist=True)
        self.feedback_lbl.configure(text=f"✔ Modelo ativo alterado para: {name}", text_color="#4ade80")
        self.refresh_models_gallery()

    def _import_zip_or_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Selecionar Modelo Live2D (.zip, .model3.json ou .model.json)",
            filetypes=[
                ("Modelos Live2D (.zip / .json)", "*.zip *.model3.json *.model.json"),
                ("Arquivo ZIP", "*.zip"),
                ("Manifesto Live2D", "*.model3.json *.model.json"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not chosen:
            return
        self._process_import(chosen)

    def _import_folder(self) -> None:
        chosen = filedialog.askdirectory(title="Selecionar Pasta do Modelo Live2D")
        if not chosen:
            return
        self._process_import(chosen)

    def _process_import(self, path_str: str) -> None:
        try:
            info = import_live2d_model(path_str)
            self.avatar.set_model_path(info.rel_path, persist=True)
            self.feedback_lbl.configure(
                text=f"✔ Modelo '{info.name}' importado e carregado com sucesso!",
                text_color="#4ade80",
            )
            self.refresh_models_gallery()
        except Exception as exc:
            self.feedback_lbl.configure(text=f"✖ Erro ao importar modelo: {exc}", text_color="#f87171")

    def _open_models_folder(self) -> None:
        MODELS_ROOT_DIR.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(MODELS_ROOT_DIR))
        except Exception:
            pass

    def _on_zoom_changed(self, value: float) -> None:
        self.zoom_val_lbl.configure(text=f"{float(value):.2f}x")
        self.avatar.set_transform(zoom=float(value))

    def _on_pos_x_changed(self, value: float) -> None:
        self.pos_x_lbl.configure(text=f"{float(value):+.0f} px")
        self.avatar.set_transform(offset_x=float(value))

    def _on_pos_y_changed(self, value: float) -> None:
        self.pos_y_lbl.configure(text=f"{float(value):+.0f} px")
        self.avatar.set_transform(offset_y=float(value))

    def _on_lipsync_changed(self, value: float) -> None:
        self.lipsync_lbl.configure(text=f"{float(value):.2f}x")
        self.avatar.set_transform(lip_sync_sensitivity=float(value))

    def _reset_transform(self) -> None:
        self.zoom_slider.set(1.0)
        self.pos_x_slider.set(0.0)
        self.pos_y_slider.set(0.0)
        self.lipsync_slider.set(1.0)
        self.zoom_val_lbl.configure(text="1.00x")
        self.pos_x_lbl.configure(text="+0 px")
        self.pos_y_lbl.configure(text="+0 px")
        self.lipsync_lbl.configure(text="1.00x")
        self.avatar.set_transform(zoom=1.0, offset_x=0.0, offset_y=0.0, lip_sync_sensitivity=1.0)

    def _trigger_sing_speak(self) -> None:
        self.avatar.trigger_action("cantar")
        if self._on_test_sing_speak:
            self._on_test_sing_speak()



# Re-export do painel de memória e armazenamento
from src.ui.memory_panel import EditFactDialog, FactCard, MemoryPanel
from src.ui.api_key_dialog import ApiKeyDialog
