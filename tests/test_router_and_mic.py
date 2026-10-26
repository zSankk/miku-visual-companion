"""Testes do roteador, memória de sessão e controlador de microfone (sem rede)."""

import pytest

from src.core.llm_client import BrainError, OfflineBrain
from src.core.router import ConversationRouter
from src.core.state import Mode
from src.voice.mic_controller import MicController, MicMutedError, list_input_devices
from src.voice.stt import SpeechToText, VoiceSettings
from src.voice.tts import TextToSpeech, clean_text_for_speech, ptbr_to_vocaloid_phonetic


class FakeBrain:
    name = "Fake"

    def __init__(self, reply="[feliz] Oi!", fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = []

    def generate(self, system_instruction, history):
        self.calls.append((system_instruction, list(history)))
        if self.fail:
            raise BrainError("sem rede")
        return self.reply


def test_router_casual_parseia_e_salva_historico(persona):
    brain = FakeBrain("[sarcasmo] Claro que sim.")
    router = ConversationRouter(persona, brain)
    reply = router.handle("Você me ama?")

    assert reply.emotion == "sarcasmo"
    assert reply.text == "Claro que sim."
    assert reply.mode is Mode.CASUAL
    assert len(router.memory) == 2
    system, history = brain.calls[0]
    assert "Conversa Casual" in system
    assert history[-1].text == "Você me ama?"


def test_router_modo_dev_usa_prompt_dev_quando_ponte_indisponivel(persona):
    brain = FakeBrain("[pensativa] Vamos ver esse bug.")
    router = ConversationRouter(persona, brain, mode=Mode.DEV)
    reply = router.handle("Tem um bug aqui")
    assert reply.mode is Mode.DEV
    assert "Dev Antigravity" in brain.calls[0][0]


def test_toggle_mode(persona):
    router = ConversationRouter(persona, FakeBrain())
    assert router.toggle_mode() is Mode.DEV
    assert router.toggle_mode() is Mode.CASUAL


def test_falha_do_cerebro_nao_corrompe_historico(persona):
    router = ConversationRouter(persona, FakeBrain(fail=True))
    with pytest.raises(BrainError):
        router.handle("oi")
    assert len(router.memory) == 0


def test_nova_sessao_limpa_memoria(persona):
    router = ConversationRouter(persona, FakeBrain())
    router.handle("oi")
    router.new_session()
    assert len(router.memory) == 0


def test_offline_brain_sempre_tem_tag(persona):
    router = ConversationRouter(persona, OfflineBrain(seed=1))
    for _ in range(10):
        assert router.handle("teste").parsed.had_valid_tag


def test_mode_from_str():
    assert Mode.from_str("dev") is Mode.DEV
    assert Mode.from_str("Dev Antigravity") is Mode.DEV
    assert Mode.from_str("xyz") is Mode.CASUAL
    assert Mode.from_str(None) is Mode.CASUAL


def test_mic_inicia_mutado_e_bloqueia_captura():
    mic = MicController()
    assert mic.is_muted
    with pytest.raises(MicMutedError):
        mic.require_capture_allowed()


def test_mic_hard_mute_libera_dispositivos_e_notifica():
    mic = MicController(start_muted=False)
    events, released = [], []
    mic.add_listener(events.append)
    mic.register_release_hook(lambda: released.append(True))

    assert mic.toggle() is True
    assert events == [True]
    assert released == [True]
    assert mic.toggle() is False
    assert events == [True, False]
    mic.require_capture_allowed()  # não lança


def test_mic_hook_com_erro_nao_impede_mute():
    mic = MicController(start_muted=False)
    mic.register_release_hook(lambda: 1 / 0)
    mic.hard_mute()
    assert mic.is_muted


def test_list_input_devices_retorna_padrao_e_dispositivos():
    devices = list_input_devices()
    assert len(devices) >= 1
    assert devices[0].index is None
    assert "Padrão" in devices[0].name


def test_mic_set_device_notifica_listeners():
    mic = MicController()
    chosen = []
    mic.add_device_listener(chosen.append)
    mic.set_device(2)
    assert mic.device_index == 2
    assert chosen == [2]


def test_stt_respeita_hard_mute():
    mic = MicController(start_muted=True)
    stt = SpeechToText(mic=mic)
    with pytest.raises(MicMutedError):
        stt.start()


def test_stt_mutar_logo_apos_falar_nao_cancela_transcricao():
    """Garante que mutar o microfone logo após terminar de falar não descarta a transcrição."""
    mic = MicController(start_muted=False)
    received = []
    stt = SpeechToText(mic=mic, on_transcript=received.append)
    stt._run_whisper_inference = lambda _pcm: ("Oi Miku, tudo bem?", 0.12)

    # Simula o usuário mutando o microfone antes/durante o fim da transcrição
    mic.hard_mute()
    assert mic.is_muted
    stt._transcribe_local(b"\x01\x00" * 1600)
    assert received == ["Oi Miku, tudo bem?"]


def test_stt_delay_e_sensibilidade_configuraveis():
    mic = MicController(start_muted=True)
    stt = SpeechToText(mic=mic, silence_duration_s=0.8, energy_threshold=0.015)
    stt.set_silence_duration(1.6)
    assert stt.silence_duration_s == 1.6
    assert stt.silence_blocks_to_end == 20  # 1.6s / 0.08s
    stt.set_energy_threshold(0.025)
    assert stt.energy_threshold == 0.025


def test_voice_settings_persistencia(tmp_path):
    cfg_file = tmp_path / "voice_settings.json"
    s = VoiceSettings(device_index=3, silence_duration_s=1.4, energy_threshold=0.022, whisper_model="small")
    s.save(cfg_file)
    loaded = VoiceSettings.load(cfg_file)
    assert loaded.device_index == 3
    assert loaded.silence_duration_s == 1.4
    assert loaded.energy_threshold == 0.022
    assert loaded.whisper_model == "small"


def test_tts_clean_text_e_prosodia_por_emocao():
    cleaned = clean_text_for_speech("[feliz] Oi **mundo**! ```python\nprint(1)\n``` Fim.")
    assert "[feliz]" not in cleaned
    assert "print(1)" not in cleaned
    assert "veja o código na tela" in cleaned
    tts = TextToSpeech(enabled=False, base_rate_pct=10, pitch_hz=15, tts_provider="miku_hf")
    rate_feliz, pitch_feliz, _, _ = tts._format_prosody("feliz")
    rate_sarcasmo, pitch_sarcasmo, _, _ = tts._format_prosody("sarcasmo")
    assert rate_feliz != rate_sarcasmo
    assert pitch_feliz != pitch_sarcasmo
    called = []
    tts.speak("teste", emotion="feliz", on_done=lambda: called.append(True))
    assert called == [True]


def test_ptbr_to_vocaloid_phonetic_transliteracao():
    out = ptbr_to_vocaloid_phonetic("Rin, você tem razão! Amanhã vou tomar café com pão e olhar o carro.")
    # 'r' inicial -> 'h', 'ç' -> 'ss', 'ão' -> 'aun', 'nh' -> 'ny', 'lh' -> 'li', 'rr' -> 'h', sem acentos
    assert out.startswith("hin,")
    assert "vosse" in out
    assert "hazaun" in out
    assert "amanyan" in out
    assert "kafe" in out or "cafe" in out
    assert "paun" in out
    assert "oliar" in out
    assert "kaho" in out or "caho" in out


def test_tts_miku_local_e_fallback_automatico_para_edge_tts():
    import numpy as np

    tts = TextToSpeech(enabled=True, tts_provider="miku_local", pitch_hz=15, volume=0.8)
    fallback_calls = []

    def _fake_miku_local_fail(_text, _emotion):
        raise RuntimeError("Erro simulado no RVC local")

    def _fake_edge(text, emotion, force_fallback_voice=False):
        fallback_calls.append((text, emotion, force_fallback_voice))
        return np.ones(2400, dtype=np.float32) * 0.5

    tts._synthesize_miku_local_pcm = _fake_miku_local_fail
    tts._synthesize_edge_pcm = _fake_edge

    pcm = tts._synthesize_pcm("Oi tudo bem", "feliz")
    assert pcm is not None
    assert len(fallback_calls) == 1
    assert fallback_calls[0] == ("Oi tudo bem", "feliz", True)
    assert np.allclose(pcm, 0.4)
