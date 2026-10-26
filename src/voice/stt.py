"""Speech-to-Text (STT) 100% Local em tempo real com Faster-Whisper + VAD configurável.

Privacidade Total (Zero Nuvem):
- Nenhum byte de áudio sai do computador do usuário.
- O modelo Faster-Whisper (`base`, `small` ou `turbo`/`large-v3-turbo` com
  quantização `int8`) fica salvo localmente em `data/models/whisper/`.
- Pipeline de alta precisão para Português Brasileiro:
  - Normalização automática de ganho (AGC) e remoção de DC offset antes da transcrição.
  - `beam_size=5` + `initial_prompt` contextualizando vocabulário PT-BR, "Rin" e dev.
  - `PRE_ROLL_BLOCKS = 10` (~800ms) para nunca engolir o início da frase.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import queue
import threading
import time
from typing import Callable

from src.voice.mic_controller import MicController

log = logging.getLogger(__name__)

# Desativa avisos de symlink do huggingface_hub no Windows
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

TranscriptCallback = Callable[[str], None]
LevelCallback = Callable[[float], None]
SpeechStateCallback = Callable[[bool], None]

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WHISPER_CACHE_DIR = PROJECT_ROOT / "data" / "models" / "whisper"
VOICE_CONFIG_PATH = PROJECT_ROOT / "data" / "voice_settings.json"

# Mapeamento de nome amigável -> identificador real do modelo no CTranslate2/HF
WHISPER_MODEL_MAP: dict[str, str] = {
    "base": "base",
    "small": "small",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}
AVAILABLE_WHISPER_MODELS: tuple[str, ...] = ("base", "small", "turbo")
DEFAULT_WHISPER_MODEL = "small"

# Prompt de contexto para guiar a ortografia e o vocabulário em PT-BR
PT_BR_INITIAL_PROMPT = (
    "Oi Miku, tudo bem? Conversa em português do Brasil sobre o dia a dia, "
    "jogos, código, Python, programação e Antigravity."
)

SAMPLE_RATE = 16000
BLOCK_DURATION_S = 0.08  # 80ms por bloco
BLOCK_SIZE = int(SAMPLE_RATE * BLOCK_DURATION_S)
PRE_ROLL_BLOCKS = 10  # ~800ms antes do início da fala (evita cortar a 1ª palavra)
MIN_SPEECH_BLOCKS = 5  # ~400ms mínimos de fala válida
MAX_SPEECH_BLOCKS = 250  # ~20s máximo por frase

# Frases "fantasmas" comuns do Whisper em silêncio/ruído de fundo
_HALLUCINATIONS = frozenset(
    {
        "obrigado.",
        "obrigado",
        "obrigada.",
        "obrigada",
        "legendas pela comunidade amara.org",
        "inscreva-se no canal",
        "tchau",
        "...",
        ".",
    }
)


def _preprocess_audio(pcm_bytes: bytes):
    """Converte PCM int16 -> float32, remove DC offset e aplica ganho automático (AGC)."""
    import numpy as np

    audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        return audio

    # Remove componente DC (centraliza a onda em 0.0)
    audio = audio - float(np.mean(audio))

    # Normalização de pico suave: amplifica microfones baixos (até 8x de ganho)
    # sem amplificar silêncio puro.
    peak = float(np.max(np.abs(audio)))
    if 0.008 < peak < 0.85:
        gain = min(8.0, 0.85 / peak)
        audio = np.clip(audio * gain, -1.0, 1.0)

    return audio


def _parse_rate_pct(rate_str: str | int | float | None, default: int = 10) -> int:
    if rate_str is None:
        return default
    if isinstance(rate_str, (int, float)):
        return int(round(rate_str))
    cleaned = str(rate_str).strip().replace("%", "").replace("+", "")
    try:
        return max(-40, min(60, int(round(float(cleaned)))))
    except ValueError:
        return default


def _parse_pitch_hz(pitch_str: str | int | float | None, default: int = 15) -> int:
    if pitch_str is None:
        return default
    if isinstance(pitch_str, (int, float)):
        return int(round(pitch_str))
    cleaned = str(pitch_str).strip().lower().replace("hz", "").replace("+", "")
    try:
        return max(-30, min(50, int(round(float(cleaned)))))
    except ValueError:
        return default


def _default_voice_from_env_or_yaml() -> dict:
    """Lê os padrões de voz do .env e do config/persona.yaml."""
    defaults = {
        "tts_provider": "miku_local",
        "miku_model": "1a_miku_default_rvc_(aple)",
        "miku_phonetic_ptbr": False,
        "miku_timeout_s": 28.0,
        "tts_voice": "pt-BR-FranciscaNeural",
        "tts_rate_pct": 10,
        "tts_pitch_hz": 15,
    }
    try:
        import yaml

        persona_file = PROJECT_ROOT / "config" / "persona.yaml"
        if persona_file.is_file():
            raw = yaml.safe_load(persona_file.read_text(encoding="utf-8")) or {}
            v = raw.get("voice") or {}
            if "tts_provider" in v:
                defaults["tts_provider"] = str(v["tts_provider"]).strip()
            if "miku_model" in v:
                defaults["miku_model"] = str(v["miku_model"]).strip()
            if "miku_phonetic_ptbr" in v:
                defaults["miku_phonetic_ptbr"] = bool(v["miku_phonetic_ptbr"])
            if "miku_timeout_s" in v:
                defaults["miku_timeout_s"] = float(v["miku_timeout_s"])
            if "tts_voice" in v:
                defaults["tts_voice"] = str(v["tts_voice"]).strip()
            if "tts_rate" in v:
                defaults["tts_rate_pct"] = _parse_rate_pct(v["tts_rate"], 10)
            if "tts_pitch" in v:
                defaults["tts_pitch_hz"] = _parse_pitch_hz(v["tts_pitch"], 15)
    except Exception:
        pass

    if os.getenv("RIN_TTS_PROVIDER"):
        defaults["tts_provider"] = os.getenv("RIN_TTS_PROVIDER", "").strip()
    if os.getenv("RIN_MIKU_MODEL"):
        defaults["miku_model"] = os.getenv("RIN_MIKU_MODEL", "").strip()
    if os.getenv("RIN_MIKU_PHONETIC_PTBR"):
        defaults["miku_phonetic_ptbr"] = os.getenv("RIN_MIKU_PHONETIC_PTBR", "true").strip().lower() in {
            "1", "true", "yes", "sim", "on",
        }
    if os.getenv("RIN_MIKU_TIMEOUT_S"):
        try:
            defaults["miku_timeout_s"] = float(os.getenv("RIN_MIKU_TIMEOUT_S", "28.0"))
        except ValueError:
            pass
    if os.getenv("RIN_TTS_VOICE"):
        defaults["tts_voice"] = os.getenv("RIN_TTS_VOICE", "").strip()
    if os.getenv("RIN_TTS_RATE"):
        defaults["tts_rate_pct"] = _parse_rate_pct(os.getenv("RIN_TTS_RATE"), defaults["tts_rate_pct"])
    if os.getenv("RIN_TTS_PITCH"):
        defaults["tts_pitch_hz"] = _parse_pitch_hz(os.getenv("RIN_TTS_PITCH"), defaults["tts_pitch_hz"])
    return defaults


@dataclass
class VoiceSettings:
    """Configurações persistentes de captura de microfone, modelo STT e voz da Rin (mikuTTS + Edge-TTS)."""

    device_index: int | None = None
    silence_duration_s: float = 1.0  # Atraso após parar de falar para começar a pensar (0.3s a 3.0s)
    energy_threshold: float = 0.012  # Sensibilidade de ativação de voz (0.003 a 0.080)
    whisper_model: str = DEFAULT_WHISPER_MODEL  # base | small | turbo
    tts_enabled: bool = True
    tts_provider: str = "miku_local"  # miku_local | miku_hf | edge_tts
    miku_model: str = "1a_miku_default_rvc_(aple)"
    miku_phonetic_ptbr: bool = False
    miku_timeout_s: float = 28.0
    tts_voice: str = "pt-BR-FranciscaNeural"
    tts_rate_pct: int = 10  # "+10%"
    tts_pitch_hz: int = 15  # "+15Hz" (usado pelo Edge-TTS / Fallback sem pedalboard)
    tts_volume: float = 0.9

    def save(self, path: Path = VOICE_CONFIG_PATH) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "device_index": self.device_index,
                "silence_duration_s": round(float(self.silence_duration_s), 2),
                "energy_threshold": round(float(self.energy_threshold), 4),
                "whisper_model": self.whisper_model,
                "tts_enabled": bool(self.tts_enabled),
                "tts_provider": self.tts_provider,
                "miku_model": self.miku_model,
                "miku_phonetic_ptbr": bool(self.miku_phonetic_ptbr),
                "miku_timeout_s": round(float(self.miku_timeout_s), 1),
                "tts_voice": self.tts_voice,
                "tts_rate_pct": int(self.tts_rate_pct),
                "tts_pitch_hz": int(self.tts_pitch_hz),
                "tts_volume": round(float(self.tts_volume), 2),
            }
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            log.warning("Não foi possível salvar configurações de voz: %s", exc)

    @classmethod
    def load(cls, path: Path = VOICE_CONFIG_PATH) -> "VoiceSettings":
        defs = _default_voice_from_env_or_yaml()
        if not path.is_file():
            return cls(**defs)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            model = str(raw.get("whisper_model", DEFAULT_WHISPER_MODEL)).strip().lower()
            if model not in AVAILABLE_WHISPER_MODELS:
                model = DEFAULT_WHISPER_MODEL
            provider = str(raw.get("tts_provider", defs["tts_provider"])).strip()
            if provider not in {"miku_local", "miku_hf", "edge_tts"}:
                provider = defs["tts_provider"]
            return cls(
                device_index=raw.get("device_index"),
                silence_duration_s=max(0.3, min(3.0, float(raw.get("silence_duration_s", 1.0)))),
                energy_threshold=max(0.002, min(0.10, float(raw.get("energy_threshold", 0.012)))),
                whisper_model=model,
                tts_enabled=bool(raw.get("tts_enabled", True)),
                tts_provider=provider,
                miku_model=str(raw.get("miku_model", defs["miku_model"])),
                miku_phonetic_ptbr=bool(raw.get("miku_phonetic_ptbr", defs["miku_phonetic_ptbr"])),
                miku_timeout_s=max(8.0, min(90.0, float(raw.get("miku_timeout_s", defs["miku_timeout_s"])))),
                tts_voice=str(raw.get("tts_voice", defs["tts_voice"])),
                tts_rate_pct=_parse_rate_pct(raw.get("tts_rate_pct", defs["tts_rate_pct"]), defs["tts_rate_pct"]),
                tts_pitch_hz=_parse_pitch_hz(raw.get("tts_pitch_hz", defs["tts_pitch_hz"]), defs["tts_pitch_hz"]),
                tts_volume=max(0.0, min(1.0, float(raw.get("tts_volume", 0.9)))),
            )
        except Exception as exc:
            log.warning("Arquivo de configuração de voz inválido, usando padrão: %s", exc)
            return cls(**defs)


class SpeechToText:
    def __init__(
        self,
        mic: MicController,
        on_transcript: TranscriptCallback | None = None,
        on_level: LevelCallback | None = None,
        on_speech_state: SpeechStateCallback | None = None,
        language: str = "pt",
        model_size: str | None = None,
        energy_threshold: float = 0.012,
        silence_duration_s: float = 1.0,
    ) -> None:
        self.mic = mic
        self.on_transcript = on_transcript
        self.on_level = on_level
        self.on_speech_state = on_speech_state
        self.language = language.split("-")[0].lower()  # "pt-BR" -> "pt"
        chosen = (model_size or os.getenv("RIN_WHISPER_MODEL", DEFAULT_WHISPER_MODEL)).strip().lower()
        self.model_size = chosen if chosen in AVAILABLE_WHISPER_MODELS else DEFAULT_WHISPER_MODEL
        self.energy_threshold = float(energy_threshold)
        self.silence_duration_s = float(silence_duration_s)

        self.listening = False
        self.paused = False  # Pausado enquanto a Rin está pensando/respondendo
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._stream_lock = threading.Lock()

        # Monitoramento (Loopback: escutar a própria voz)
        self._loopback_stream = None
        self._loopback_lock = threading.Lock()

        self._whisper = None
        self._whisper_loaded_size: str | None = None
        self._whisper_lock = threading.Lock()

        # Vínculos automáticos com o MicController
        self.mic.register_release_hook(self.stop_all)
        self.mic.add_listener(self._on_mic_mute_changed)
        self.mic.add_device_listener(self._on_device_changed)

    # ------------------------------------------------- parâmetros dinâmicos
    @property
    def silence_blocks_to_end(self) -> int:
        return max(3, int(round(self.silence_duration_s / BLOCK_DURATION_S)))

    def set_silence_duration(self, seconds: float) -> None:
        self.silence_duration_s = max(0.3, min(3.0, float(seconds)))
        log.info(
            "Tempo de atraso pós-fala ajustado para %.2fs (%d blocos)",
            self.silence_duration_s,
            self.silence_blocks_to_end,
        )

    def set_energy_threshold(self, threshold: float) -> None:
        self.energy_threshold = max(0.002, min(0.10, float(threshold)))

    def set_model_size(self, model_size: str, preload: bool = True) -> None:
        model_size = model_size.strip().lower()
        if model_size not in AVAILABLE_WHISPER_MODELS:
            raise ValueError(f"Modelo inválido: {model_size}")
        if model_size == self.model_size and self._whisper is not None:
            return
        self.model_size = model_size
        if preload:
            self.preload_model_async()

    def preload_model_async(self, on_ready: Callable[[str], None] | None = None) -> None:
        """Pré-carrega o modelo Faster-Whisper em background para resposta instantânea."""
        def _task() -> None:
            try:
                self._get_whisper()
                if on_ready:
                    on_ready(self.model_size)
            except Exception as exc:
                log.error("Erro ao carregar Faster-Whisper (%s): %s", self.model_size, exc)

        threading.Thread(target=_task, daemon=True, name="rin-whisper-load").start()

    def _get_whisper(self):
        with self._whisper_lock:
            if self._whisper is None or self._whisper_loaded_size != self.model_size:
                from faster_whisper import WhisperModel

                WHISPER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                target = self.model_size
                hf_repo = WHISPER_MODEL_MAP.get(target, target)
                log.info(
                    "Carregando modelo STT 100%% local: faster-whisper (%s -> %s, int8)...",
                    target,
                    hf_repo,
                )
                self._whisper = WhisperModel(
                    hf_repo,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=max(2, os.cpu_count() or 4),
                    download_root=str(WHISPER_CACHE_DIR),
                )
                self._whisper_loaded_size = target
                log.info("Modelo Faster-Whisper (%s) local pronto!", target)
            return self._whisper

    def _run_whisper_inference(self, pcm_bytes: bytes) -> tuple[str, float]:
        """Executa o pré-processamento de áudio + transcrição de alta precisão."""
        audio_f32 = _preprocess_audio(pcm_bytes)
        model = self._get_whisper()
        t0 = time.monotonic()
        segments, _info = model.transcribe(
            audio_f32,
            language=self.language,
            beam_size=5,
            best_of=5,
            temperature=0.0,
            initial_prompt=PT_BR_INITIAL_PROMPT,
            without_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=250, speech_pad_ms=250),
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip()).strip()
        elapsed = time.monotonic() - t0
        return text, elapsed

    # ---------------------------------------------- loopback (ouvir o mic)
    @property
    def is_loopback_active(self) -> bool:
        with self._loopback_lock:
            return self._loopback_stream is not None

    def start_loopback(self, on_level: LevelCallback | None = None) -> None:
        """Reproduz o áudio do microfone selecionado direto na saída padrão (para teste)."""
        self.stop_loopback()
        if self.listening:
            self.stop()
            time.sleep(0.1)
        import numpy as np
        import sounddevice as sd

        device_in = self.mic.device_index
        device_out = None
        if device_in is not None:
            try:
                in_info = sd.query_devices(device_in)
                in_hostapi = in_info.get("hostapi")
                for idx, d in enumerate(sd.query_devices()):
                    if d.get("max_output_channels", 0) > 0 and d.get("hostapi") == in_hostapi:
                        device_out = idx
                        break
            except Exception:
                pass

        def _calc_level(indata) -> None:
            if on_level:
                samples = indata.astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                lvl = min(1.0, rms / max(0.001, self.energy_threshold * 3.5))
                try:
                    on_level(lvl)
                except Exception:
                    pass

        stream = None
        try:
            def _cb_duplex(indata, outdata, _frames, _time, _status) -> None:
                outdata[:] = indata
                _calc_level(indata)

            stream = sd.Stream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=(device_in, device_out),
                channels=1,
                dtype="int16",
                callback=_cb_duplex,
            )
        except Exception as exc:
            log.warning("Loopback duplex indisponível (%s, %s): %s. Usando InputStream.", device_in, device_out, exc)
            def _cb_input(indata, _frames, _time, _status) -> None:
                _calc_level(indata)

            stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=device_in,
                channels=1,
                dtype="int16",
                callback=_cb_input,
            )
        with self._loopback_lock:
            self._loopback_stream = stream
        stream.start()
        log.info("Teste de escuta do microfone (loopback) iniciado")

    def stop_loopback(self) -> None:
        with self._loopback_lock:
            stream = self._loopback_stream
            self._loopback_stream = None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass
            log.info("Teste de escuta do microfone (loopback) encerrado")

    # ----------------------------------- gravação de teste do modelo STT
    def record_and_transcribe_test(
        self,
        duration_s: float = 3.5,
        on_level: LevelCallback | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> tuple[str, float]:
        """Grava `duration_s` segundos do microfone selecionado e devolve `(texto, tempo_inferencia_s)`.

        Pausa temporariamente o stream contínuo para evitar conflito de hardware no Windows.
        """
        import numpy as np
        import sounddevice as sd

        was_listening = self.listening and not self.mic.is_muted
        if was_listening:
            self.stop()
            time.sleep(0.12)

        try:
            device_in = self.mic.device_index
            chunks: list[bytes] = []
            total_blocks = max(1, int(round(duration_s / BLOCK_DURATION_S)))

            def _cb(indata, _frames, _time, _status) -> None:
                raw = bytes(indata)
                chunks.append(raw)
                if on_level:
                    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                    lvl = min(1.0, rms / max(0.001, self.energy_threshold * 3.5))
                    try:
                        on_level(lvl)
                    except Exception:
                        pass

            with sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=device_in,
                channels=1,
                dtype="int16",
                callback=_cb,
            ):
                for i in range(total_blocks):
                    remaining = max(0.0, duration_s - (i * BLOCK_DURATION_S))
                    if on_status and i % 4 == 0:
                        try:
                            on_status(f"🔴 Gravando sua voz... ({remaining:.1f}s restantes)")
                        except Exception:
                            pass
                    time.sleep(BLOCK_DURATION_S)

            if on_level:
                try:
                    on_level(0.0)
                except Exception:
                    pass

            if on_status:
                try:
                    on_status(f"⏳ Transcrevendo localmente com modelo '{self.model_size}'...")
                except Exception:
                    pass

            pcm_bytes = b"".join(chunks)
            return self._run_whisper_inference(pcm_bytes)
        finally:
            if was_listening and not self.mic.is_muted:
                try:
                    self.start()
                except Exception:
                    pass

    # ---------------------------------------------- controle de captura contínua
    def _on_mic_mute_changed(self, muted: bool) -> None:
        if muted:
            self.stop_all()
        else:
            self.start()

    def _on_device_changed(self, _device_index: int | None) -> None:
        if self.listening and not self.mic.is_muted:
            log.info("Reiniciando captura no novo microfone...")
            self.stop()
            self.start()
        if self.is_loopback_active:
            self.start_loopback()

    def start(self) -> None:
        """Inicia a escuta contínua se o microfone não estiver em Hard Mute."""
        self.mic.require_capture_allowed()
        if self.listening:
            return
        self._stop_event.clear()
        self.listening = True
        self.preload_model_async()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True, name="rin-stt")
        self._thread.start()

    def stop(self) -> None:
        """Fecha imediatamente o stream físico de reconhecimento de voz."""
        self._stop_event.set()
        self.listening = False
        with self._stream_lock:
            stream = self._stream
            self._stream = None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass
        if self.on_level:
            try:
                self.on_level(0.0)
            except Exception:
                pass

    def stop_all(self) -> None:
        """Fecha tanto o stream de STT quanto eventual loopback de teste."""
        self.stop_loopback()
        self.stop()

    # --------------------------------------------------------- loop de captura
    def _capture_loop(self) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as exc:
            log.error("Dependências de áudio ausentes (sounddevice/numpy): %s", exc)
            self.listening = False
            return

        audio_q: queue.Queue[bytes] = queue.Queue()

        def _callback(indata, _frames, _time_info, status) -> None:
            if status:
                log.debug("sounddevice status: %s", status)
            if not self._stop_event.is_set() and not self.paused:
                audio_q.put(bytes(indata))

        device = self.mic.device_index
        try:
            stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                device=device,
                channels=1,
                dtype="int16",
                callback=_callback,
            )
            with self._stream_lock:
                if self._stop_event.is_set():
                    stream.close()
                    return
                self._stream = stream
            stream.start()
            log.info(
                "Escuta 100%% local ativa (device=%s, modelo=%s, atraso=%.2fs)",
                device if device is not None else "Padrão",
                self.model_size,
                self.silence_duration_s,
            )
        except Exception as exc:
            log.error("Falha ao abrir microfone (device=%s): %s", device, exc)
            self.listening = False
            return

        pre_roll: deque[bytes] = deque(maxlen=PRE_ROLL_BLOCKS)
        speech_frames: list[bytes] = []
        in_speech = False
        silence_blocks = 0
        last_level_emit = 0.0

        try:
            while not self._stop_event.is_set() and not self.mic.is_muted:
                try:
                    raw_block = audio_q.get(timeout=0.15)
                except queue.Empty:
                    continue

                samples = np.frombuffer(raw_block, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0

                now = time.monotonic()
                if self.on_level and (now - last_level_emit) >= 0.08:
                    last_level_emit = now
                    level = min(1.0, rms / max(0.001, self.energy_threshold * 3.5))
                    try:
                        self.on_level(level)
                    except Exception:
                        pass

                is_voice = rms >= self.energy_threshold

                if not in_speech:
                    pre_roll.append(raw_block)
                    if is_voice:
                        in_speech = True
                        silence_blocks = 0
                        speech_frames = list(pre_roll)
                        pre_roll.clear()
                        if self.on_speech_state:
                            try:
                                self.on_speech_state(True)
                            except Exception:
                                pass
                else:
                    speech_frames.append(raw_block)
                    if is_voice:
                        silence_blocks = 0
                    else:
                        silence_blocks += 1

                    if silence_blocks >= self.silence_blocks_to_end or len(speech_frames) >= MAX_SPEECH_BLOCKS:
                        in_speech = False
                        if self.on_speech_state:
                            try:
                                self.on_speech_state(False)
                            except Exception:
                                pass
                        if len(speech_frames) >= MIN_SPEECH_BLOCKS:
                            pcm_bytes = b"".join(speech_frames)
                            threading.Thread(
                                target=self._transcribe_local,
                                args=(pcm_bytes,),
                                daemon=True,
                            ).start()
                        speech_frames = []
                        silence_blocks = 0
        finally:
            with self._stream_lock:
                s = self._stream
                self._stream = None
            if s is not None:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass
            self.listening = False

            # Se o usuário clicou em Mutar logo após falar (estilo Push-to-Talk),
            # drena os últimos blocos já capturados na fila e envia a fala para transcrição
            # em vez de cancelar/descartar o que foi dito!
            while True:
                try:
                    tail_block = audio_q.get_nowait()
                except queue.Empty:
                    break
                if in_speech:
                    speech_frames.append(tail_block)
                else:
                    samples = np.frombuffer(tail_block, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(samples * samples))) if samples.size else 0.0
                    if rms >= self.energy_threshold:
                        in_speech = True
                        speech_frames = list(pre_roll) + [tail_block]
                        pre_roll.clear()
                    else:
                        pre_roll.append(tail_block)

            if in_speech:
                if self.on_speech_state:
                    try:
                        self.on_speech_state(False)
                    except Exception:
                        pass
                if len(speech_frames) >= 2:
                    pcm_bytes = b"".join(speech_frames)
                    threading.Thread(
                        target=self._transcribe_local,
                        args=(pcm_bytes,),
                        daemon=True,
                    ).start()

    def _transcribe_local(self, pcm_bytes: bytes) -> None:
        """Transcreve o áudio 100% localmente usando Faster-Whisper.
        Não descarta áudio já gravado se o usuário mutar o microfone logo após terminar de falar.
        """
        try:
            text, elapsed = self._run_whisper_inference(pcm_bytes)
            if not text or text.lower() in _HALLUCINATIONS:
                return
            if self.on_transcript:
                log.info("Voz reconhecida localmente (%.2fs, %s): %r", elapsed, self.model_size, text)
                self.on_transcript(text)
        except Exception as exc:
            log.warning("Falha na transcrição local (Faster-Whisper): %s", exc)
