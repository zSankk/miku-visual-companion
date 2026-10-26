"""Painel de Gerenciamento da Memória Persistente e Armazenamento da Miku.

Fornece interface completa para:
- Visualização e alteração do local do banco SQLite (.db) com migração automática.
- Exportação e importação de backups em formato JSON (.json).
- Ativação/Desativação da memória de longo prazo (modo amnésia/privacidade).
- Nova Sessão inteligente (resumo conciso gerado por IA antes de limpar).
- CRUD completo de fatos com busca em tempo real, filtros por categoria e fixação rápida (Pin).
- Visualização e remoção de resumos de sessões anteriores.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from src.memory.long_term import (
    CATEGORIES,
    Fact,
    MemoryStore,
    SensitiveDataError,
    Summary,
    is_sensitive,
    normalize_category,
)
from src.ui import theme

log = logging.getLogger(__name__)

# Paleta de cores para categorias
_CATEGORY_COLORS: dict[str, str] = {
    "pessoal": "#818cf8",      # Índigo suave
    "preferencia": "#ec4899",  # Rosa/Pink
    "projeto": "#10b981",      # Esmeralda
    "outros": "#94a3b8",       # Cinza neutro
}

_PIN_COLOR = "#f59e0b"         # Âmbar / Dourado


# =============================================================================
# Modal de Criação / Edição de Fato
# =============================================================================
class EditFactDialog(ctk.CTkToplevel):
    """Modal para adicionar ou editar uma memória com validação de privacidade."""

    def __init__(
        self,
        master,
        store: MemoryStore,
        fact: Fact | None = None,
        on_saved: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color=theme.BG_APP)
        self.store = store
        self.fact = fact
        self.on_saved = on_saved

        is_edit = fact is not None
        self.title("Editar Memória" if is_edit else "Nova Memória")
        self.geometry("520x460")
        self.minsize(460, 400)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        # Layout
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Cabeçalho
        title_text = f"✏️ Editar Memória #{fact.id}" if is_edit else "➕ Adicionar Nova Memória"
        header = ctk.CTkLabel(
            self,
            text=title_text,
            font=ctk.CTkFont(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        header.grid(row=0, column=0, sticky="w", padx=20, pady=(20, 10))

        # Categoria
        cat_frame = ctk.CTkFrame(self, fg_color="transparent")
        cat_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        cat_label = ctk.CTkLabel(
            cat_frame,
            text="Categoria:",
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.TEXT_MUTED,
        )
        cat_label.pack(side="left", padx=(0, 10))

        self.cat_var = ctk.StringVar(value=(fact.category if fact else "outros").capitalize())
        self.cat_menu = ctk.CTkOptionMenu(
            cat_frame,
            values=[c.capitalize() for c in CATEGORIES],
            variable=self.cat_var,
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            dropdown_fg_color=theme.BG_CARD,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self.cat_menu.pack(side="left")

        # Confiança
        conf_label = ctk.CTkLabel(
            cat_frame,
            text="Tipo:",
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.TEXT_MUTED,
        )
        conf_label.pack(side="left", padx=(20, 10))

        self.conf_var = ctk.StringVar(value=(fact.confidence if fact else "confirmado").capitalize())
        self.conf_menu = ctk.CTkOptionMenu(
            cat_frame,
            values=["Confirmado", "Inferencia"],
            variable=self.conf_var,
            fg_color=theme.BG_CARD,
            button_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            dropdown_fg_color=theme.BG_CARD,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self.conf_menu.pack(side="left")

        # Checkbox Fixar
        self.pin_var = ctk.BooleanVar(value=bool(fact.is_pinned) if fact else False)
        self.pin_check = ctk.CTkCheckBox(
            self,
            text="📌 Fixar Memória (Sempre incluir no prompt inicial)",
            variable=self.pin_var,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            text_color=_PIN_COLOR,
            fg_color=_PIN_COLOR,
            hover_color="#d97706",
        )
        self.pin_check.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 10))

        # Campo de Texto
        self.text_box = ctk.CTkTextbox(
            self,
            fg_color=theme.BG_INPUT,
            border_width=1,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13),
            wrap="word",
        )
        self.text_box.grid(row=3, column=0, sticky="nsew", padx=20, pady=(0, 10))
        if fact:
            self.text_box.insert("1.0", fact.content)

        # Label de Erro
        self.error_label = ctk.CTkLabel(
            self,
            text="",
            text_color="#ef4444",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
        )
        self.error_label.grid(row=4, column=0, sticky="w", padx=20, pady=(0, 10))

        # Botões de Ação
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=5, column=0, sticky="e", padx=20, pady=(0, 20))

        cancel_btn = ctk.CTkButton(
            btn_frame,
            text="Cancelar",
            fg_color=theme.BG_CARD,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_MUTED,
            width=90,
            command=self.destroy,
        )
        cancel_btn.pack(side="right", padx=(10, 0))

        save_btn = ctk.CTkButton(
            btn_frame,
            text="Salvar",
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            width=100,
            command=self._save,
        )
        save_btn.pack(side="right")

    def _save(self) -> None:
        content = self.text_box.get("1.0", "end").strip()
        if not content:
            self.error_label.configure(text="⚠️ O conteúdo da memória não pode estar vazio.")
            return

        if is_sensitive(content):
            self.error_label.configure(
                text="🔒 Trava de Privacidade: senhas, chaves de API ou dados sensíveis são bloqueados."
            )
            return

        category = self.cat_var.get().lower()
        confidence = self.conf_var.get().lower()
        is_pinned = bool(self.pin_var.get())

        try:
            if self.fact is None:
                self.store.add_fact(
                    content=content,
                    category=category,
                    confidence=confidence,
                    is_pinned=is_pinned,
                )
            else:
                self.store.update_fact(
                    fact_id=self.fact.id,
                    content=content,
                    category=category,
                    confidence=confidence,
                    is_pinned=is_pinned,
                )
            if self.on_saved:
                self.on_saved()
            self.destroy()
        except SensitiveDataError:
            self.error_label.configure(text="🔒 Trava de Privacidade: dados sensíveis detectados.")
        except Exception as exc:
            self.error_label.configure(text=f"Erro ao salvar: {exc}")


# =============================================================================
# Cartão Visual de Fato (Lista)
# =============================================================================
class FactCard(ctk.CTkFrame):
    """Exibe um fato individual com badges, indicador de fixação e botões de ação rápida."""

    def __init__(
        self,
        master,
        fact: Fact,
        on_toggle_pin: Callable[[Fact], None],
        on_edit: Callable[[Fact], None],
        on_delete: Callable[[Fact], None],
    ) -> None:
        border_color = _PIN_COLOR if fact.is_pinned else theme.BORDER
        border_width = 2 if fact.is_pinned else 1
        super().__init__(
            master,
            fg_color=theme.BG_CARD,
            corner_radius=10,
            border_width=border_width,
            border_color=border_color,
        )
        self.fact = fact
        self.on_toggle_pin = on_toggle_pin
        self.on_edit = on_edit
        self.on_delete = on_delete

        self.grid_columnconfigure(1, weight=1)

        # Topo do cartão: Badges e Botões de Ação
        top_bar = ctk.CTkFrame(self, fg_color="transparent")
        top_bar.grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 4))
        top_bar.grid_columnconfigure(0, weight=1)

        badges_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        badges_frame.grid(row=0, column=0, sticky="w")

        # Badge de Fixação
        if fact.is_pinned:
            pin_badge = ctk.CTkLabel(
                badges_frame,
                text="📌 FIXADA",
                fg_color="#451a03",
                text_color=_PIN_COLOR,
                corner_radius=6,
                font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
                padx=6,
                pady=2,
            )
            pin_badge.pack(side="left", padx=(0, 6))

        # Badge de Categoria
        cat_color = _CATEGORY_COLORS.get(fact.category, "#94a3b8")
        cat_badge = ctk.CTkLabel(
            badges_frame,
            text=fact.category.upper(),
            fg_color=theme.BG_APP,
            text_color=cat_color,
            corner_radius=6,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
            padx=8,
            pady=2,
        )
        cat_badge.pack(side="left", padx=(0, 6))

        # Badge de Confiança
        conf_text = "✓ Confirmado" if fact.confidence == "confirmado" else "~ Inferência"
        conf_badge = ctk.CTkLabel(
            badges_frame,
            text=conf_text,
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
        )
        conf_badge.pack(side="left", padx=(0, 6))

        # Botões de Ação no topo direito
        actions_frame = ctk.CTkFrame(top_bar, fg_color="transparent")
        actions_frame.grid(row=0, column=1, sticky="e")

        pin_btn_text = "Desafixar" if fact.is_pinned else "📌 Fixar"
        pin_btn_fg = "#78350f" if fact.is_pinned else theme.BG_APP
        self.pin_btn = ctk.CTkButton(
            actions_frame,
            text=pin_btn_text,
            width=70,
            height=24,
            fg_color=pin_btn_fg,
            hover_color=theme.BORDER,
            text_color=_PIN_COLOR if fact.is_pinned else theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=lambda: self.on_toggle_pin(self.fact),
        )
        self.pin_btn.pack(side="left", padx=2)

        self.edit_btn = ctk.CTkButton(
            actions_frame,
            text="✏️",
            width=28,
            height=24,
            fg_color=theme.BG_APP,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=lambda: self.on_edit(self.fact),
        )
        self.edit_btn.pack(side="left", padx=2)

        self.del_btn = ctk.CTkButton(
            actions_frame,
            text="🗑️",
            width=28,
            height=24,
            fg_color=theme.BG_APP,
            hover_color="#7f1d1d",
            text_color="#f87171",
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=lambda: self.on_delete(self.fact),
        )
        self.del_btn.pack(side="left", padx=2)

        # Conteúdo do Fato
        content_label = ctk.CTkLabel(
            self,
            text=fact.content,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 13),
            wraplength=460,
            justify="left",
            anchor="w",
        )
        content_label.grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 10))


# =============================================================================
# Painel Principal: Aba "🧠 Memória & Armazenamento"
# =============================================================================
class MemoryPanel(ctk.CTkFrame):
    """Painel de controle visual e armazenamento de memória da Miku."""

    def __init__(
        self,
        master,
        memory_store: MemoryStore,
        on_archive_session: Callable[[], str | None] | None = None,
        on_status_message: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.store = memory_store
        self.on_archive_session = on_archive_session
        self.on_status_message = on_status_message

        self._active_category = "todas"
        self._search_query = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        self._build_storage_card()
        self._build_controls_bar()
        self._build_search_filter_bar()
        self._build_facts_list()
        self._build_summaries_section()

        self.refresh()

    # ------------------------------------------------------------------ 1. Painel de Armazenamento (Topo)
    def _build_storage_card(self) -> None:
        card = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER,
        )
        card.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 10))
        card.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(card, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        header_row.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header_row,
            text="💾 ARMAZENAMENTO & BANCO DE DADOS LOCAL",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=0, sticky="w")

        # Botões de Ação de Armazenamento
        btn_box = ctk.CTkFrame(header_row, fg_color="transparent")
        btn_box.grid(row=0, column=1, sticky="e")

        change_dir_btn = ctk.CTkButton(
            btn_box,
            text="📁 Alterar Pasta",
            height=28,
            fg_color=theme.BG_APP,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            command=self._change_storage_directory,
        )
        change_dir_btn.pack(side="left", padx=4)

        export_btn = ctk.CTkButton(
            btn_box,
            text="📤 Exportar Backup",
            height=28,
            fg_color=theme.BG_APP,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=self._export_backup,
        )
        export_btn.pack(side="left", padx=4)

        import_btn = ctk.CTkButton(
            btn_box,
            text="📥 Importar Backup",
            height=28,
            fg_color=theme.BG_APP,
            hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            command=self._import_backup,
        )
        import_btn.pack(side="left", padx=4)

        # Linha com o caminho completo do arquivo .db
        self.path_label = ctk.CTkLabel(
            card,
            text=f"Local: {self.store.db_path}",
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
            anchor="w",
            wraplength=640,
        )
        self.path_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

    # ------------------------------------------------------------------ 2. Controles de Privacidade & Sessão
    def _build_controls_bar(self) -> None:
        bar = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CARD,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER,
        )
        bar.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 10))
        bar.grid_columnconfigure(1, weight=1)

        # Switch Memória Ativa
        switch_frame = ctk.CTkFrame(bar, fg_color="transparent")
        switch_frame.grid(row=0, column=0, sticky="w", padx=14, pady=10)

        self.memory_switch_var = ctk.BooleanVar(value=self.store.enabled)
        self.memory_switch = ctk.CTkSwitch(
            switch_frame,
            text="Memória Ativa",
            variable=self.memory_switch_var,
            onvalue=True,
            offvalue=False,
            command=self._on_toggle_memory_enabled,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            progress_color=theme.ACCENT,
        )
        self.memory_switch.pack(side="left")

        self.memory_state_hint = ctk.CTkLabel(
            switch_frame,
            text="● Ativa (Lembrando fatos)" if self.store.enabled else "○ Modo Amnésia (Privado)",
            text_color=theme.ACCENT if self.store.enabled else theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11),
        )
        self.memory_state_hint.pack(side="left", padx=(10, 0))

        # Botões da Direita: Nova Sessão Inteligente & Adicionar Memória
        btn_box = ctk.CTkFrame(bar, fg_color="transparent")
        btn_box.grid(row=0, column=1, sticky="e", padx=14, pady=10)

        new_session_btn = ctk.CTkButton(
            btn_box,
            text="🔄 Nova Sessão (Resumir e Limpar)",
            height=32,
            fg_color="#047857",
            hover_color="#065f46",
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._trigger_new_session_summary,
        )
        new_session_btn.pack(side="left", padx=4)

        add_btn = ctk.CTkButton(
            btn_box,
            text="➕ Nova Memória",
            height=32,
            fg_color=theme.ACCENT,
            hover_color=theme.ACCENT_HOVER,
            text_color="#ffffff",
            font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            command=self._open_new_fact_dialog,
        )
        add_btn.pack(side="left", padx=4)

    # ------------------------------------------------------------------ 3. Barra de Busca e Filtro
    def _build_search_filter_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)

        # Campo de Busca em Tempo Real
        self.search_entry = ctk.CTkEntry(
            bar,
            placeholder_text="🔍 Filtrar memórias em tempo real...",
            fg_color=theme.BG_CARD,
            border_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            height=34,
            font=ctk.CTkFont(theme.FONT_FAMILY, 12),
        )
        self.search_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.search_entry.bind("<KeyRelease>", self._on_search_typed)

        # Filtro de Categorias SegmentedButton
        self.cat_filter = ctk.CTkSegmentedButton(
            bar,
            values=["Todas", "Pessoal", "Preferência", "Projeto", "Outros"],
            command=self._on_category_filter_selected,
            selected_color=theme.ACCENT,
            selected_hover_color=theme.ACCENT_HOVER,
            fg_color=theme.BG_CARD,
            unselected_color=theme.BG_CARD,
            unselected_hover_color=theme.BORDER,
            text_color=theme.TEXT_PRIMARY,
            font=ctk.CTkFont(theme.FONT_FAMILY, 11, "bold"),
            height=34,
        )
        self.cat_filter.set("Todas")
        self.cat_filter.grid(row=0, column=1, sticky="e")

    # ------------------------------------------------------------------ 4. Lista Rolável de Fatos
    def _build_facts_list(self) -> None:
        self.facts_container = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            label_text="🧠 Fatos & Preferências Memorizados",
            label_font=ctk.CTkFont(theme.FONT_FAMILY, 12, "bold"),
            label_text_color=theme.TEXT_MUTED,
        )
        self.facts_container.grid(row=3, column=0, sticky="nsew", padx=0, pady=(0, 8))
        self.facts_container.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ 5. Seção de Resumos Anteriores
    def _build_summaries_section(self) -> None:
        self.summaries_frame = ctk.CTkFrame(
            self,
            fg_color=theme.BG_CARD,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER,
        )
        self.summaries_frame.grid(row=4, column=0, sticky="ew", padx=0, pady=(0, 0))
        self.summaries_frame.grid_columnconfigure(0, weight=1)

        header_row = ctk.CTkFrame(self.summaries_frame, fg_color="transparent")
        header_row.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        header_row.grid_columnconfigure(0, weight=1)

        self.summaries_title = ctk.CTkLabel(
            header_row,
            text="📜 RESUMOS DE CONVERSAS ANTERIORES (ÚLTIMAS SESSÕES)",
            text_color=theme.TEXT_MUTED,
            font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
            anchor="w",
        )
        self.summaries_title.grid(row=0, column=0, sticky="w")

        clear_all_btn = ctk.CTkButton(
            header_row,
            text="Limpar Tudo",
            height=20,
            width=80,
            fg_color="transparent",
            hover_color="#7f1d1d",
            text_color="#f87171",
            font=ctk.CTkFont(theme.FONT_FAMILY, 10),
            command=self._confirm_clear_all,
        )
        clear_all_btn.grid(row=0, column=1, sticky="e")

        self.summaries_content = ctk.CTkFrame(self.summaries_frame, fg_color="transparent")
        self.summaries_content.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 8))
        self.summaries_content.grid_columnconfigure(0, weight=1)

    # ------------------------------------------------------------------ Atualização / Renderização
    def refresh(self) -> None:
        """Recarrega a lista de fatos e resumos com base nos filtros atuais."""
        self.path_label.configure(text=f"Local: {self.store.db_path.resolve()}")

        # Limpa widgets de fatos
        for child in self.facts_container.winfo_children():
            child.destroy()

        facts = self.store.list_facts(
            category=self._active_category,
            search=self._search_query,
        )

        if not facts:
            msg = "Nenhuma memória encontrada."
            if self._search_query:
                msg = f"Nenhuma memória encontrada para '{self._search_query}'."
            empty_lbl = ctk.CTkLabel(
                self.facts_container,
                text=msg,
                text_color=theme.TEXT_MUTED,
                font=ctk.CTkFont(theme.FONT_FAMILY, 12, slant="italic"),
                pady=30,
            )
            empty_lbl.pack(fill="x")
        else:
            for fact in facts:
                card = FactCard(
                    self.facts_container,
                    fact=fact,
                    on_toggle_pin=self._on_toggle_pin,
                    on_edit=self._open_edit_fact_dialog,
                    on_delete=self._on_delete_fact,
                )
                card.pack(fill="x", pady=4)

        # Atualiza seção de resumos
        self._refresh_summaries()

    def _refresh_summaries(self) -> None:
        for child in self.summaries_content.winfo_children():
            child.destroy()

        summaries = self.store.list_summaries(limit=3)
        if not summaries:
            lbl = ctk.CTkLabel(
                self.summaries_content,
                text="Nenhum resumo registrado ainda (use 'Nova Sessão' para resumir conversas longas).",
                text_color=theme.TEXT_MUTED,
                font=ctk.CTkFont(theme.FONT_FAMILY, 11, slant="italic"),
                anchor="w",
            )
            lbl.pack(fill="x", pady=2)
            return

        for s in summaries:
            row = ctk.CTkFrame(self.summaries_content, fg_color="transparent")
            row.pack(fill="x", pady=2)
            row.grid_columnconfigure(1, weight=1)

            date_badge = ctk.CTkLabel(
                row,
                text=s.created_at[:10],
                text_color=theme.TEXT_MUTED,
                font=ctk.CTkFont(theme.FONT_FAMILY, 10, "bold"),
                width=75,
                anchor="w",
            )
            date_badge.grid(row=0, column=0, sticky="w")

            text_lbl = ctk.CTkLabel(
                row,
                text=f"• {s.summary_text}",
                text_color=theme.TEXT_PRIMARY,
                font=ctk.CTkFont(theme.FONT_FAMILY, 11),
                anchor="w",
                justify="left",
                wraplength=520,
            )
            text_lbl.grid(row=0, column=1, sticky="w")

            del_btn = ctk.CTkButton(
                row,
                text="✕",
                width=20,
                height=18,
                fg_color="transparent",
                hover_color="#7f1d1d",
                text_color="#f87171",
                font=ctk.CTkFont(theme.FONT_FAMILY, 9),
                command=lambda sid=s.id: self._on_delete_summary(sid),
            )
            del_btn.grid(row=0, column=2, sticky="e", padx=(4, 0))

    # ------------------------------------------------------------------ Eventos e Ações
    def _on_toggle_memory_enabled(self) -> None:
        enabled = bool(self.memory_switch_var.get())
        self.store.set_enabled(enabled)
        if enabled:
            self.memory_state_hint.configure(
                text="● Ativa (Lembrando fatos)", text_color=theme.ACCENT
            )
            if self.on_status_message:
                self.on_status_message("Memória de longo prazo ativada.")
        else:
            self.memory_state_hint.configure(
                text="○ Modo Amnésia (Privado)", text_color=theme.TEXT_MUTED
            )
            if self.on_status_message:
                self.on_status_message("Modo amnésia ativado: nenhuma memória será lida ou gravada.")

    def _on_category_filter_selected(self, choice: str) -> None:
        self._active_category = choice.lower()
        self.refresh()

    def _on_search_typed(self, event=None) -> None:
        self._search_query = self.search_entry.get().strip()
        self.refresh()

    def _open_new_fact_dialog(self) -> None:
        EditFactDialog(self, store=self.store, fact=None, on_saved=self.refresh)

    def _open_edit_fact_dialog(self, fact: Fact) -> None:
        EditFactDialog(self, store=self.store, fact=fact, on_saved=self.refresh)

    def _on_toggle_pin(self, fact: Fact) -> None:
        self.store.set_pinned(fact.id, not fact.is_pinned)
        self.refresh()

    def _on_delete_fact(self, fact: Fact) -> None:
        if messagebox.askyesno("Excluir Memória", f"Deseja excluir a memória:\n\n\"{fact.content}\"?"):
            self.store.delete_fact(fact.id)
            self.refresh()

    def _on_delete_summary(self, summary_id: int) -> None:
        self.store.delete_summary(summary_id)
        self._refresh_summaries()

    def _trigger_new_session_summary(self) -> None:
        if self.on_archive_session:
            summary = self.on_archive_session()
            self.refresh()
            if summary:
                messagebox.showinfo("Nova Sessão", f"Resumo registrado com sucesso:\n\n{summary}")

    def _change_storage_directory(self) -> None:
        chosen = filedialog.askdirectory(title="Selecione o novo diretório para o banco de dados")
        if not chosen:
            return

        try:
            new_path = self.store.change_storage_directory(chosen, migrate_existing=True)
            self.refresh()
            messagebox.showinfo(
                "Armazenamento Migrado",
                f"Banco de dados migrado com sucesso para:\n{new_path}",
            )
        except Exception as exc:
            log.error("Erro ao alterar pasta do banco: %s", exc)
            messagebox.showerror("Erro de Migração", f"Não foi possível migrar o banco: {exc}")

    def _export_backup(self) -> None:
        dest = filedialog.asksaveasfilename(
            title="Exportar Backup de Memória",
            defaultextension=".json",
            filetypes=[("Arquivo JSON", "*.json")],
            initialfile="miku_memory_backup.json",
        )
        if not dest:
            return

        try:
            data = self.store.export_backup_json()
            Path(dest).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            facts_count = len(data.get("facts", []))
            summaries_count = len(data.get("summaries", []))
            messagebox.showinfo(
                "Backup Exportado",
                f"Backup salvo com sucesso em:\n{dest}\n\n• {facts_count} memórias\n• {summaries_count} resumos",
            )
        except Exception as exc:
            log.error("Erro ao exportar backup: %s", exc)
            messagebox.showerror("Erro de Exportação", f"Falha ao exportar backup: {exc}")

    def _import_backup(self) -> None:
        src = filedialog.askopenfilename(
            title="Importar Backup de Memória",
            filetypes=[("Arquivo JSON", "*.json")],
        )
        if not src:
            return

        try:
            raw = Path(src).read_text(encoding="utf-8")
            data = json.loads(raw)
            facts_cnt, summs_cnt = self.store.import_backup_json(data)
            self.refresh()
            messagebox.showinfo(
                "Backup Importado",
                f"Backup importado com sucesso!\n\n• {facts_cnt} memórias adicionadas/atualizadas\n• {summs_cnt} resumos adicionados",
            )
        except Exception as exc:
            log.error("Erro ao importar backup: %s", exc)
            messagebox.showerror("Erro de Importação", f"Falha ao ler arquivo de backup: {exc}")

    def _confirm_clear_all(self) -> None:
        if messagebox.askyesno(
            "Limpar Banco de Dados",
            "⚠️ Tem certeza de que deseja apagar TODAS as memórias e resumos?\nEsta ação não pode ser desfeita.",
        ):
            self.store.clear_all()
            self.refresh()
