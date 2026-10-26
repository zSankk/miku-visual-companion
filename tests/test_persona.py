"""Testes de carregamento e validação do config/persona.yaml."""

import pytest
import yaml

from src.core.persona import REQUIRED_EMOTIONS, PersonaError, load_persona, persona_from_dict
from src.core.state import Mode


def test_persona_carrega_com_campos_basicos(persona):
    assert persona.name == "Miku"
    assert persona.language == "pt-BR"
    assert persona.default_emotion == "neutra"
    assert persona.system_prompt.strip()


def test_persona_tem_todas_as_emocoes_obrigatorias(persona):
    assert set(REQUIRED_EMOTIONS) <= set(persona.emotions)


def test_system_prompt_exige_tag_de_emocao(persona):
    prompt = persona.system_prompt
    assert "DEVE começar" in prompt
    for emotion in REQUIRED_EMOTIONS:
        assert f"[{emotion}]" in prompt


def test_tracos_de_personalidade(persona):
    traits = " ".join(persona.traits).lower()
    for trait in ("brincalhona", "direta", "carinhosa", "teimosa", "sarcástica"):
        assert trait in traits


def test_prompt_por_modo_inclui_complemento(persona):
    casual = persona.build_system_instruction(Mode.CASUAL)
    dev = persona.build_system_instruction(Mode.DEV)
    assert casual.startswith(persona.system_prompt.strip())
    assert "Conversa Casual" in casual
    assert "Dev Antigravity" in dev
    assert casual != dev


def test_parametros_de_geracao(persona):
    assert 0.0 <= persona.temperature <= 2.0
    assert persona.max_output_tokens > 0


def test_arquivo_inexistente_gera_erro(tmp_path):
    with pytest.raises(PersonaError, match="não encontrado"):
        load_persona(tmp_path / "nao_existe.yaml")


def test_yaml_invalido_gera_erro(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: Rin\nemotions: [neutra\n", encoding="utf-8")
    with pytest.raises(PersonaError, match="YAML inválido"):
        load_persona(bad)


def _base_dict(persona_path):
    return yaml.safe_load(persona_path.read_text(encoding="utf-8"))


def test_emocao_obrigatoria_ausente_gera_erro(persona_path):
    data = _base_dict(persona_path)
    data["emotions"].remove("sarcasmo")
    with pytest.raises(PersonaError, match="sarcasmo"):
        persona_from_dict(data)


def test_campo_obrigatorio_ausente_gera_erro(persona_path):
    data = _base_dict(persona_path)
    del data["system_prompt"]
    with pytest.raises(PersonaError, match="system_prompt"):
        persona_from_dict(data)


def test_prompt_sem_regra_de_tags_gera_erro(persona_path):
    data = _base_dict(persona_path)
    data["system_prompt"] = "Você é a Rin. Seja legal."
    with pytest.raises(PersonaError, match="tags de emoção"):
        persona_from_dict(data)


def test_default_emotion_invalida_gera_erro(persona_path):
    data = _base_dict(persona_path)
    data["default_emotion"] = "eufórica"
    with pytest.raises(PersonaError, match="default_emotion"):
        persona_from_dict(data)
