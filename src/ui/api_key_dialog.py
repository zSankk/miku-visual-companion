"""Modal de configuração da GEMINI_API_KEY e seleção de modelo dentro do aplicativo."""

from __future__ import annotations

import logging
import webbrowser
from typing import Callable

import customtkinter as ctk

from src.core.settings import DEFAULT_MODEL, Settings, save_api_credentials
from src.ui import theme

log = logging.getLogger(__name__)

AVAILABLE_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
)


class ApiKeyDialog(ctk.CTkToplevel):
    """Modal para visualizar, cadastrar ou atualizar a chave da API do Gemini e o modelo ativo."""

    def __init__(
        self,
        master,
        settings: Settings,
        on_saved: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color=theme.BG_APP)
        self.settings = settings
        self.on_saved = on_saved
        self._key_visible = False

        self.title("Configurar Chave de API (Gemini)")
        self.geometry("560x550")
        self.minsize(460, 400)
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self._center_window(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _center_window(self, master) -> None:
        try:
            self.update_idletasks()
            w, h = 560, 550
            mw = master.winfo_width()
            mh = master.winfo_height()
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            x = max(20, mx + (mw - w) // 2)
            y = max(20, my + (mh - h) // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

    def _build_ui(self) -> None:
        # 1. Barra de Ações Fixa no Rodapé (SEMPRE visível, imune a DPI e scroll)
        btn_box = ctk.CTkFrame(self, fg_color="transparent", height=50)
        btn_box.pack(side="bottom", fill="x", padx=20, pady=(10, 16))

        remove_btn = ctk.CTkButton(
            btn_box,
            text="Desativar Chave",
            fg_color="transparent",
            hover_color="#7f1d1d",
            text_color="#f87171",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            height=36,
            command=self._clear_key,
        )
        remove_btn.pack(side="left")

        cancel_btn = ctk.CTkButton(
            btn_box,
            text="Cancelar",
            fg_color=theme.BG_CARD,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=36,
            width=90,
            command=self.destroy,
        )
        cancel_btn.pack(side="right", padx=(10, 0))

        save_btn = ctk.CTkButton(
            btn_box,
            text="💾 Salvar e Aplicar",
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            height=36,
            width=140,
            command=self._save,
        )
        save_btn.pack(side="right")

        # 2. Área rolável com o conteúdo (suporta qualquer tamanho de tela / DPI)
        content = ctk.CTkScrollableFrame(self, fg_color="transparent")
        content.pack(side="top", fill="both", expand=True, padx=16, pady=(16, 0))
        content.grid_columnconfigure(0, weight=1)

        # Cabeçalho
        head_frame = ctk.CTkFrame(content, fg_color="transparent")
        head_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 12))
        head_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            head_frame,
            text="🔑 Configurar Chave de API (Gemini)",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 16, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")

        ctk.CTkLabel(
            head_frame,
            text="Insira sua GEMINI_API_KEY do Google AI Studio para ativar as respostas inteligentes da Miku.",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
            wraplength=460,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        # Card de Status Atual
        status_card = ctk.CTkFrame(
            content,
            fg_color=theme.BG_CARD,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
        )
        status_card.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 14))
        status_card.grid_columnconfigure(1, weight=1)

        if self.settings.has_api_key and self.settings.api_key:
            k = self.settings.api_key
            masked = f"{k[:7]}...{k[-4:]}" if len(k) > 12 else "********"
            status_text = f"● Chave configurada: {masked}"
            status_color = "#4ade80"
        else:
            status_text = "○ Nenhuma chave configurada (Modo Offline / Simulado)"
            status_color = "#facc15"

        ctk.CTkLabel(
            status_card,
            text="STATUS ATUAL:",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=14, pady=10)

        ctk.CTkLabel(
            status_card,
            text=status_text,
            text_color=status_color,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w", padx=(6, 14), pady=10)

        # Campo de Entrada da Chave
        key_frame = ctk.CTkFrame(content, fg_color="transparent")
        key_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 12))
        key_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            key_frame,
            text="Nova Chave de API (GEMINI_API_KEY):",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))

        self.key_entry = ctk.CTkEntry(
            key_frame,
            placeholder_text="Cole sua chave aqui (AIzaSy...)",
            show="*",
            height=36,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self.key_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        if self.settings.api_key:
            self.key_entry.insert(0, self.settings.api_key)
        self.key_entry.bind("<Return>", lambda _e: self._save())

        self.eye_btn = ctk.CTkButton(
            key_frame,
            text="👁️",
            width=36,
            height=36,
            fg_color=theme.BG_CARD,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            command=self._toggle_eye,
        )
        self.eye_btn.grid(row=1, column=1, sticky="e")

        # Botão link para obter chave gratuita
        link_btn = ctk.CTkButton(
            key_frame,
            text="🌐 Obter chave gratuita no Google AI Studio (aistudio.google.com)",
            fg_color="transparent",
            hover_color=theme.BG_CARD,
            text_color="#60a5fa",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, underline=True),
            anchor="w",
            height=24,
            command=lambda: webbrowser.open("https://aistudio.google.com/app/apikey"),
        )
        link_btn.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        # Seleção de Modelo
        model_frame = ctk.CTkFrame(content, fg_color="transparent")
        model_frame.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 12))
        model_frame.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            model_frame,
            text="Modelo Gemini:",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))

        cur_model = self.settings.model if self.settings.model in AVAILABLE_GEMINI_MODELS else DEFAULT_MODEL
        self.model_var = ctk.StringVar(value=cur_model)
        self.model_menu = ctk.CTkOptionMenu(
            model_frame,
            values=list(AVAILABLE_GEMINI_MODELS),
            variable=self.model_var,
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            dropdown_fg_color=theme.BG_CARD,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
            height=32,
        )
        self.model_menu.grid(row=0, column=1, sticky="ew")

        ctk.CTkLabel(
            model_frame,
            text="Dica: 'gemini-3.5-flash-lite' é o padrão leve e rápido. Em caso de oscilação nos servidores do Google, o aplicativo alterna automaticamente para modelos de fallback.",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            anchor="w",
            wraplength=460,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # Feedback Label
        self.feedback_lbl = ctk.CTkLabel(
            content,
            text="",
            text_color="#ef4444",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
            wraplength=460,
            justify="left",
        )
        self.feedback_lbl.grid(row=4, column=0, sticky="w", padx=6, pady=(0, 10))

    def _toggle_eye(self) -> None:
        self._key_visible = not self._key_visible
        self.key_entry.configure(show="" if self._key_visible else "*")
        self.eye_btn.configure(text="🔒" if self._key_visible else "👁️")

    def _save(self) -> None:
        key = self.key_entry.get().strip()
        model = self.model_var.get().strip() or DEFAULT_MODEL

        if not key:
            self.feedback_lbl.configure(text="⚠️ A chave de API não pode estar vazia. Cole sua chave acima.")
            return

        try:
            save_api_credentials(api_key=key, model=model)
            if self.on_saved:
                self.on_saved(key, model)
            self.destroy()
        except Exception as exc:
            log.error("Erro ao salvar GEMINI_API_KEY: %s", exc)
            self.feedback_lbl.configure(text=f"Erro ao salvar: {exc}")

    def _clear_key(self) -> None:
        try:
            model = self.model_var.get().strip() or DEFAULT_MODEL
            save_api_credentials(api_key="", model=model)
            if self.on_saved:
                self.on_saved("", model)
            self.destroy()
        except Exception as exc:
            self.feedback_lbl.configure(text=f"Erro ao desativar: {exc}")
