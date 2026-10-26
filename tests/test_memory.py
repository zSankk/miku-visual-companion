"""Testes automatizados do Sistema Avançado de Memória Persistente SQLite da Miku."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from src.core.emotion_parser import parse_reply
from src.core.llm_client import Brain
from src.core.persona import Persona
from src.core.router import ConversationRouter
from src.core.state import Mode
from src.memory.long_term import (
    Fact,
    MemoryStore,
    SensitiveDataError,
    StorageConfig,
    is_sensitive,
    normalize_category,
    normalize_confidence,
)


@pytest.fixture
def temp_store(tmp_path: Path) -> MemoryStore:
    db_file = tmp_path / "test_memory.db"
    cfg_file = tmp_path / "test_settings.json"
    cfg = StorageConfig(db_path=db_file, memory_enabled=True)
    return MemoryStore(config=cfg, db_path=db_file, config_path=cfg_file)


# =============================================================================
# 1. Filtro de Privacidade (Regex)
# =============================================================================
def test_privacy_filter_blocks_sensitive_patterns():
    # Chaves de API
    assert is_sensitive("Minha chave é AIzaSyD9876543210abcdefghijklmnopq")
    assert is_sensitive("sk-proj-1234567890abcdef123456")
    assert is_sensitive("ghp_1234567890abcdefghijklmnopqrstuv")

    # Senhas e segredos
    assert is_sensitive("minha senha secreta é miku123")
    assert is_sensitive("meu password de root é admin")
    assert is_sensitive("Chave de API do sistema: 1234")

    # Documentos e cartões
    assert is_sensitive("CPF: 123.456.789-00")
    assert is_sensitive("Cartão de crédito: 4111 2222 3333 4444")


def test_privacy_filter_allows_normal_user_facts():
    assert not is_sensitive("O usuário se chama Lucas e adora café sem açúcar.")
    assert not is_sensitive("Mora em São Paulo e trabalha com Python.")
    assert not is_sensitive("Prefere a Hatsune Miku com o modelo clássico.")
    assert not is_sensitive("O projeto atual se chama Miku Visual Companion.")


# =============================================================================
# 2. CRUD de Fatos (facts)
# =============================================================================
def test_add_and_get_fact(temp_store: MemoryStore):
    fact = temp_store.add_fact(
        content="Gosta de café puro pela manhã",
        category="preferencia",
        confidence="confirmado",
        is_pinned=True,
    )
    assert fact.id is not None
    assert fact.content == "Gosta de café puro pela manhã"
    assert fact.category == "preferencia"
    assert fact.confidence == "confirmado"
    assert fact.is_pinned is True

    loaded = temp_store.get_fact(fact.id)
    assert loaded is not None
    assert loaded.content == fact.content
    assert loaded.is_pinned is True


def test_add_fact_rejects_sensitive_data(temp_store: MemoryStore):
    with pytest.raises(SensitiveDataError):
        temp_store.add_fact("A chave da API é AIzaSyA1234567890abcdefghijk")


def test_update_fact(temp_store: MemoryStore):
    fact = temp_store.add_fact("Trabalha com Java", category="projeto")
    updated = temp_store.update_fact(fact.id, content="Trabalha com Python e Rust", category="projeto", is_pinned=True)

    assert updated is not None
    assert updated.content == "Trabalha com Python e Rust"
    assert updated.is_pinned is True

    reloaded = temp_store.get_fact(fact.id)
    assert reloaded is not None
    assert reloaded.content == "Trabalha com Python e Rust"


def test_set_pinned(temp_store: MemoryStore):
    fact = temp_store.add_fact("Mora em Curitiba", category="pessoal", is_pinned=False)
    assert fact.is_pinned is False

    pinned = temp_store.set_pinned(fact.id, True)
    assert pinned is not None
    assert pinned.is_pinned is True

    unpinned = temp_store.set_pinned(fact.id, False)
    assert unpinned is not None
    assert unpinned.is_pinned is False


def test_delete_fact(temp_store: MemoryStore):
    fact = temp_store.add_fact("Gosta de chá verde", category="preferencia")
    assert temp_store.delete_fact(fact.id) is True
    assert temp_store.get_fact(fact.id) is None
    assert temp_store.delete_fact(fact.id) is False


def test_list_facts_filtering_and_search(temp_store: MemoryStore):
    temp_store.add_fact("Adora cantar músicas Vocaloid", category="preferencia", is_pinned=True)
    temp_store.add_fact("Desenvolve em Flutter e Python", category="projeto")
    temp_store.add_fact("Mora perto da praia", category="pessoal")

    all_facts = temp_store.list_facts()
    assert len(all_facts) == 3
    # Fato fixado vem primeiro
    assert all_facts[0].is_pinned is True

    proj_facts = temp_store.list_facts(category="projeto")
    assert len(proj_facts) == 1
    assert "Flutter" in proj_facts[0].content

    search_facts = temp_store.list_facts(search="Vocaloid")
    assert len(search_facts) == 1
    assert search_facts[0].category == "preferencia"


# =============================================================================
# 3. Resumos de Sessão (summaries)
# =============================================================================
def test_summaries_crud(temp_store: MemoryStore):
    s1 = temp_store.add_summary("Conversaram sobre o novo modelo Live2D da Miku.")
    s2 = temp_store.add_summary("O usuário pediu ajuda para configurar atalhos no Windows.")

    assert s1 is not None and s2 is not None
    summaries = temp_store.list_summaries()
    assert len(summaries) == 2
    # Mais recente primeiro
    assert summaries[0].summary_text == "O usuário pediu ajuda para configurar atalhos no Windows."

    assert temp_store.delete_summary(s1.id) is True
    assert len(temp_store.list_summaries()) == 1


# =============================================================================
# 4. Recuperação Contextual Enxuta (Prompt Injection)
# =============================================================================
def test_get_context_for_prompt_priority(temp_store: MemoryStore):
    # Fato fixado essencial
    temp_store.add_fact("Nome do usuário é Alex", category="pessoal", is_pinned=True)
    # Fato não fixado mas altamente relevante
    temp_store.add_fact("Alex ama gatos siameses", category="preferencia", is_pinned=False)
    # Fato não fixado irrelevante
    temp_store.add_fact("Gosta de pizza de quatro queijos", category="preferencia", is_pinned=False)
    # Resumo anterior
    temp_store.add_summary("Na sessão anterior, conversaram sobre adoção de animais.")

    prompt_ctx = temp_store.get_context_for_prompt("Quantos gatos você acha que eu deveria ter?")

    assert "Nome do usuário é Alex" in prompt_ctx
    assert "Alex ama gatos siameses" in prompt_ctx
    assert "adoção de animais" in prompt_ctx


def test_get_context_empty_when_disabled(temp_store: MemoryStore):
    temp_store.add_fact("Usuário é desenvolvedor", category="projeto", is_pinned=True)
    assert temp_store.get_context_for_prompt("Olá") != ""

    temp_store.set_enabled(False)
    assert temp_store.get_context_for_prompt("Olá") == ""


# =============================================================================
# 5. Parser de Tags [MEMORIA: ...] na Resposta da IA
# =============================================================================
def test_emotion_parser_extracts_memory_tags():
    raw = (
        "[feliz][acao: acenar] Anotadíssimo! Vou sempre lembrar disso! "
        "[MEMORIA: preferencia | O usuário ama café sem açúcar | confirmado]"
    )
    parsed = parse_reply(raw)
    assert parsed.emotion == "feliz"
    assert parsed.action == "acenar"
    assert "[MEMORIA" not in parsed.text
    assert parsed.text == "Anotadíssimo! Vou sempre lembrar disso!"
    assert len(parsed.memories) == 1
    assert parsed.memories[0].category == "preferencia"
    assert parsed.memories[0].content == "O usuário ama café sem açúcar"
    assert parsed.memories[0].confidence == "confirmado"


# =============================================================================
# 6. Integração do Router com a Memória Persistente
# =============================================================================
class MockBrain(Brain):
    def __init__(self, reply: str) -> None:
        self.reply = reply

    @property
    def name(self) -> str:
        return "MockBrain"

    def generate(self, system_instruction: str, turns: list) -> str:
        return self.reply


def test_router_auto_saves_memory_tag_and_injects_in_next_turn(persona: Persona, temp_store: MemoryStore):
    brain = MockBrain(
        "[feliz] Fechado! [MEMORIA: pessoal | Usuário mora no Brasil | confirmado]"
    )
    router = ConversationRouter(
        persona=persona,
        brain=brain,
        long_term=temp_store,
        mode=Mode.CASUAL,
    )

    # Turno 1: IA gera resposta com tag [MEMORIA: ...]
    reply = router.handle("Eu moro no Brasil.")
    assert reply.text == "Fechado!"

    # Verifica se o fato foi gravado no banco SQLite
    facts = temp_store.list_facts()
    assert len(facts) == 1
    assert facts[0].content == "Usuário mora no Brasil"
    assert facts[0].category == "pessoal"

    # Turno 2: Bloco contextual deve conter o fato gravado
    ctx = temp_store.get_context_for_prompt("Onde eu moro?")
    assert "Usuário mora no Brasil" in ctx


def test_router_amnesia_mode_does_not_save_memory(persona: Persona, temp_store: MemoryStore):
    brain = MockBrain(
        "[feliz] Entendi. [MEMORIA: preferencia | Prefere usar Linux | confirmado]"
    )
    router = ConversationRouter(
        persona=persona,
        brain=brain,
        long_term=temp_store,
        mode=Mode.CASUAL,
    )

    # Ativa modo amnésia / desativa memória
    temp_store.set_enabled(False)
    router.handle("Eu prefiro Linux.")

    # Nenhum fato deve ter sido salvo
    assert len(temp_store.list_facts()) == 0


def test_router_archive_and_new_session(persona: Persona, temp_store: MemoryStore):
    brain = MockBrain("[neutra] Conversaram sobre programação em Python.")
    router = ConversationRouter(
        persona=persona,
        brain=brain,
        long_term=temp_store,
        mode=Mode.CASUAL,
    )

    # Simula conversa com pelo menos 2 turnos
    router.memory.add_user("Como usar Python com SQLite?")
    router.memory.add_model("Basta usar a biblioteca sqlite3 embutida.", "feliz", "[feliz] Basta usar...")

    summary = router.archive_and_new_session()
    assert summary is not None
    assert "programação em Python" in summary

    # Verifica se foi persistido na tabela summaries
    summaries = temp_store.list_summaries()
    assert len(summaries) == 1
    assert "programação em Python" in summaries[0].summary_text
    # Histórico de sessão atual foi limpo
    assert len(router.memory) == 0


# =============================================================================
# 7. Troca de Diretório com Migração Automática
# =============================================================================
def test_change_storage_directory_migrates_data(tmp_path: Path):
    initial_db = tmp_path / "origin" / "miku_memory.db"
    cfg_file = tmp_path / "settings.json"
    store = MemoryStore(
        config=StorageConfig(db_path=initial_db, memory_enabled=True),
        db_path=initial_db,
        config_path=cfg_file,
    )

    store.add_fact("Memória original salva antes de migrar", category="projeto", is_pinned=True)

    # Seleciona nova pasta de destino
    new_dir = tmp_path / "novo_local"
    new_db_file = store.change_storage_directory(new_dir, migrate_existing=True)

    assert new_db_file.is_file()
    assert new_db_file.parent == new_dir
    assert store.db_path == new_db_file

    # Dados devem continuar intactos no novo arquivo
    facts = store.list_facts()
    assert len(facts) == 1
    assert facts[0].content == "Memória original salva antes de migrar"
    assert facts[0].is_pinned is True


# =============================================================================
# 8. Exportação e Importação de Backup (.json)
# =============================================================================
def test_export_and_import_backup_json(temp_store: MemoryStore, tmp_path: Path):
    temp_store.add_fact("Primeiro fato", category="pessoal", is_pinned=True)
    temp_store.add_fact("Segundo fato", category="preferencia", is_pinned=False)
    temp_store.add_summary("Resumo de teste da sessão")

    backup = temp_store.export_backup_json()
    assert len(backup["facts"]) == 2
    assert len(backup["summaries"]) == 1

    # Cria um novo banco em branco
    fresh_db = tmp_path / "fresh.db"
    fresh_store = MemoryStore(
        config=StorageConfig(db_path=fresh_db),
        db_path=fresh_db,
        config_path=tmp_path / "fresh_settings.json",
    )
    assert len(fresh_store.list_facts()) == 0

    # Importa o backup gerado
    f_cnt, s_cnt = fresh_store.import_backup_json(backup)
    assert f_cnt == 2
    assert s_cnt == 1

    imported_facts = fresh_store.list_facts()
    assert len(imported_facts) == 2
    assert any(f.content == "Primeiro fato" and f.is_pinned for f in imported_facts)


def test_router_reply_contains_saved_memories(persona: Persona, temp_store: MemoryStore):
    brain = MockBrain("[feliz] Ok! [MEMORIA: preferencia | Gosta de música rock | confirmado]")
    router = ConversationRouter(persona=persona, brain=brain, long_term=temp_store, mode=Mode.CASUAL)
    reply = router.handle("Eu adoro rock clássico.")
    assert len(reply.saved_memories) == 1
    assert reply.saved_memories[0].content == "Gosta de música rock"
    assert reply.saved_memories[0].category == "preferencia"
