"""Testes do parser de emoções."""

import pytest

from src.core.emotion_parser import VALID_EMOTIONS, normalize_emotion, parse_reply


@pytest.mark.parametrize("emotion", sorted(VALID_EMOTIONS))
def test_extrai_cada_emocao_valida(emotion):
    parsed = parse_reply(f"[{emotion}] Olá, tudo bem?")
    assert parsed.emotion == emotion
    assert parsed.text == "Olá, tudo bem?"
    assert parsed.had_valid_tag is True


def test_preserva_resposta_bruta():
    raw = "[feliz] Oi!"
    assert parse_reply(raw).raw == raw


@pytest.mark.parametrize(
    "raw, emotion, text",
    [
        ("   \n[feliz]   Oi!", "feliz", "Oi!"),
        ("[Pensativa] Hmm...", "pensativa", "Hmm..."),
        ("[SURPRESA] Sério?!", "surpresa", "Sério?!"),
        ("[ sarcasmo ] Que surpresa.", "sarcasmo", "Que surpresa."),
        ("**[irritada]** Para com isso.", "irritada", "Para com isso."),
        ("`[neutra]` Ok.", "neutra", "Ok."),
        ("[feliz]: Oba!", "feliz", "Oba!"),
        ("[feliz]Sem espaço.", "feliz", "Sem espaço."),
        ("[feliz]\nLinha nova.", "feliz", "Linha nova."),
    ],
)
def test_formatos_tolerados(raw, emotion, text):
    parsed = parse_reply(raw)
    assert parsed.emotion == emotion
    assert parsed.text == text


@pytest.mark.parametrize(
    "alias, expected",
    [("sarcástica", "sarcasmo"), ("brava", "irritada"), ("alegre", "feliz"), ("pensativo", "pensativa")],
)
def test_sinonimos_sao_normalizados(alias, expected):
    assert normalize_emotion(alias) == expected
    assert parse_reply(f"[{alias}] texto").emotion == expected


def test_sem_tag_usa_emocao_padrao():
    parsed = parse_reply("Esqueci a tag.")
    assert parsed.emotion == "neutra"
    assert parsed.text == "Esqueci a tag."
    assert parsed.had_valid_tag is False


def test_tag_invalida_usa_padrao_e_mantem_texto():
    parsed = parse_reply("[eufórica] Uhuu!")
    assert parsed.emotion == "neutra"
    assert parsed.text == "[eufórica] Uhuu!"
    assert parsed.had_valid_tag is False


def test_default_customizado():
    assert parse_reply("sem tag", default_emotion="pensativa").emotion == "pensativa"


@pytest.mark.parametrize("raw", ["", None, "   "])
def test_resposta_vazia(raw):
    parsed = parse_reply(raw)
    assert parsed.emotion == "neutra"
    assert parsed.text == ""


def test_apenas_a_primeira_tag_define_a_emocao_e_tags_extras_somem():
    parsed = parse_reply("[feliz] Oi! [irritada] Brincadeira.")
    assert parsed.emotion == "feliz"
    assert "[" not in parsed.text
    assert parsed.text == "Oi! Brincadeira."


def test_colchetes_legitimos_sao_preservados():
    parsed = parse_reply("[pensativa] Use a lista [1, 2, 3] e o índice [i].")
    assert parsed.emotion == "pensativa"
    assert parsed.text == "Use a lista [1, 2, 3] e o índice [i]."


def test_tag_no_meio_nao_e_tratada_como_inicial():
    parsed = parse_reply("Oi [feliz] tudo bem")
    assert parsed.emotion == "neutra"
    assert parsed.had_valid_tag is False
    assert parsed.text == "Oi tudo bem"
