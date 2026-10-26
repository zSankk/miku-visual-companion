"""Módulo de Voz Sintetizada da Rin (Miku RVC Local + Space John6666/mikuTTS + Fallback Edge-TTS).

Arquitetura Completa (Zero Pedalboard / Zero Efeito de Esquilo):
1. Limpa qualquer tag de emoção residual (`[feliz]`, `[irritada]`, etc.) e blocos de código.
2. Provedor Padrão (`tts_provider="miku_local"`):
   - Executa **localmente na sua máquina** o pipeline completo do `John6666/mikuTTS`:
     - Voz base PT-BR idêntica à usada no site: `pt-BR-FranciscaNeural-Female` (`pt-BR-FranciscaNeural`).
     - Extrator de features `hubert_base.pt` + extrator de pitch de alta precisão `rmvpe.pt` (`RMVPE`).
     - Modelo RVC da Hatsune Miku `1a_miku_default_rvc_(aple)` (`miku_default_rvc.pth` + índice FAISS `.index`)
       com `f0_up_key=6`, `index_rate=0.75`, `protect=0.33`.
3. Provedor Space Remoto (`tts_provider="miku_hf"`):
   - Envia para `Client("John6666/mikuTTS")` (`api_name="/tts"`) garantindo `speed`, `volume` e `pitch`
     como **inteiros** (`int`) para nunca causar `ValueError: Invalid rate '+15.0%'` no `edge-tts` remoto,
     usando `pt-BR-FranciscaNeural-Female` (ou `ja-JP-NanamiNeural-Female` se a adaptação fonética Romaji
     estiver ativada).
4. Fallback Automático de Segurança:
   - Se `miku_hf` falhar, tenta o motor **Miku RVC Local**; se indisponível, usa automaticamente o
     `edge-tts` puro (`pitch='+15Hz'`, sem `pedalboard`) para a Rin nunca ficar muda.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import io
import logging
import os
from pathlib import Path
import queue
import re
import threading
import unicodedata
from typing import Callable

log = logging.getLogger(__name__)

TTS_SAMPLE_RATE = 24000
MIKU_SPACE_ID = "John6666/mikuTTS"
MIKU_API_NAME = "/tts"
MIKU_PTBR_SPEAKER = "pt-BR-FranciscaNeural-Female"
MIKU_JA_SPEAKER = "ja-JP-NanamiNeural-Female"

AVAILABLE_TTS_PROVIDERS: dict[str, str] = {
    "Miku RVC Instalado Localmente (pt-BR-FranciscaNeural-Female + RMVPE)": "miku_local",
    "Hatsune Miku Space Remota (John6666/mikuTTS + Fallback)": "miku_hf",
    "Edge-TTS Neural Puro (+15Hz sem RVC)": "edge_tts",
}
DEFAULT_TTS_PROVIDER = "miku_local"

AVAILABLE_MIKU_MODELS: dict[str, str] = {
    "Miku Default RVC (aple) - Instalado Localmente": "1a_miku_default_rvc_(aple)",
    "Miku Mellow Suave (aple)": "1b_miku_mellow_rvc_(aple)",
    "Miku Sweet Vocaloid": "hatsunemikusweet",
    "Hatsune Miku V2 - VOCALOID (250 Epoch)": "Hatsune Miku V2 - VOCALOID (RVC) 250 Epoch",
    "Mitchie M Miku Revamped (bluchew)": "2_mitchieMmiku_revamped (bluchew)",
    "Miku V4X (bluchew)": "mikuv4xforbluchew",
    "Miku AI": "MikuAI",
}
DEFAULT_MIKU_MODEL = "1a_miku_default_rvc_(aple)"

AVAILABLE_PT_VOICES: dict[str, str] = {
    "Francisca Neural (Voz PT-BR oficial do mikuTTS)": "pt-BR-FranciscaNeural",
    "Thalita Neural (Jovem & Suave)": "pt-BR-ThalitaNeural",
    "Letícia Neural (+15Hz Fallback)": "pt-BR-LeticiaNeural",
    "Giovanna Neural (Animada)": "pt-BR-GiovannaNeural",
    "Brenda Neural (Calma & Direta)": "pt-BR-BrendaNeural",
}
DEFAULT_VOICE_ID = "pt-BR-FranciscaNeural"

# Cadeia de vozes neurais PT-BR ativas para nunca falhar caso a Microsoft desative algum endpoint
_EDGE_FALLBACK_CHAIN: tuple[str, ...] = (
    "pt-BR-FranciscaNeural",
    "pt-BR-ThalitaNeural",
    "pt-BR-LeticiaNeural",
)


@dataclass(frozen=True)
class EmotionModulation:
    rate_delta_pct: int  # variação extra de velocidade (%)
    pitch_delta_hz: int  # variação extra de pitch (Hz)


EMOTION_MODULATION: dict[str, EmotionModulation] = {
    "neutra": EmotionModulation(rate_delta_pct=0, pitch_delta_hz=0),
    "feliz": EmotionModulation(rate_delta_pct=+5, pitch_delta_hz=+3),
    "irritada": EmotionModulation(rate_delta_pct=+6, pitch_delta_hz=-2),
    "sarcasmo": EmotionModulation(rate_delta_pct=-5, pitch_delta_hz=-3),
    "surpresa": EmotionModulation(rate_delta_pct=+8, pitch_delta_hz=+5),
    "pensativa": EmotionModulation(rate_delta_pct=-6, pitch_delta_hz=-2),
}

_LEADING_OR_INLINE_TAG_RE = re.compile(
    r"\[\s*(?:neutra|feliz|irritada|sarcasmo|surpresa|pensativa|(?:acao|ação|emote|action)\s*:\s*[^\[\]\n]+)\s*\]",
    re.IGNORECASE,
)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```")
_MARKDOWN_CLEAN_RE = re.compile(r"[*_`~#>]+")


def clean_text_for_speech(text: str) -> str:
    """Remove qualquer tag `[emocao]` residual, blocos de código e markdown antes de falar."""
    cleaned = _LEADING_OR_INLINE_TAG_RE.sub("", text or "")
    cleaned = _CODE_BLOCK_RE.sub(" veja o código na tela. ", cleaned)
    cleaned = _MARKDOWN_CLEAN_RE.sub("", cleaned)
    return " ".join(cleaned.split()).strip()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…;])\s+|\n+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[,:—])\s+")


def split_speech_clauses(text: str, first_max_chars: int = 65) -> list[str]:
    """Divide o texto em cláusulas curtas para síntese em pipeline (streaming por frase).

    A primeira frase fica bem enxuta (até ~65 caracteres) para começar a tocar quase
    instantaneamente (<0.4s), enquanto as frases seguintes são sintetizadas em paralelo
    em background durante a reprodução da primeira.
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned:
        return []
    if len(cleaned) <= first_max_chars:
        return [cleaned]

    raw_sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(cleaned) if s and s.strip()]
    if not raw_sentences:
        return [cleaned]

    # Se a primeira frase for longa e tiver vírgula, divide na primeira vírgula para resposta imediata
    clauses: list[str] = []
    first = raw_sentences[0]
    if len(first) > first_max_chars:
        sub = [p.strip() for p in _CLAUSE_SPLIT_RE.split(first) if p and p.strip()]
        if len(sub) >= 2 and len(sub[0]) >= 12:
            clauses.append(sub[0])
            clauses.append(" ".join(sub[1:]))
        else:
            clauses.append(first)
    else:
        clauses.append(first)

    for sent in raw_sentences[1:]:
        # Agrupa frases muito curtinhas (< 18 chars) com a anterior, exceto a cláusula #0
        if len(clauses) >= 2 and len(clauses[-1]) + len(sent) < 75:
            clauses[-1] = f"{clauses[-1]} {sent}"
        else:
            clauses.append(sent)

    return [c for c in clauses if c]


def _strip_accents(text: str) -> str:
    """Remove acentos gráficos preservando as letras base (á/â/à -> a, é/ê -> e, etc.)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def ptbr_to_vocaloid_phonetic(text: str) -> str:
    """Translitera texto em Português Brasileiro para Romaji/Fonético estilo Vocaloid.

    Útil quando o modo fonético japonês (`ja-JP-NanamiNeural-Female`) é ativado:
    - `'ções' -> 'ssoins'`, `'ção' -> 'ssaun'`, `'ão' -> 'aun'`, `'ões' -> 'oins'`, `'ãe' -> 'ain'`
    - `'nh' -> 'ny'`, `'lh' -> 'li'`, `'ç' -> 'ss'`, `'ch' -> 'sh'`
    - `'rr' -> 'h'` e `'r'` inicial `-> 'h'`
    - `'qu'` antes de `e/i` `-> 'k'`, `'gu'` antes de `e/i` `-> 'g'`
    - Remove acentos gráficos mantendo a pronúncia aberta.
    """
    if not text:
        return ""

    s = text.strip().lower()

    nasal_rules = (
        ("ções", "ssoins"),
        ("ção", "ssaun"),
        ("sões", "zoins"),
        ("são", "zaun"),
        ("ões", "oins"),
        ("ães", "ains"),
        ("ãos", "auns"),
        ("ão", "aun"),
        ("ãe", "ain"),
        ("õe", "oin"),
        ("ã", "an"),
        ("õ", "on"),
    )
    for src, dst in nasal_rules:
        s = s.replace(src, dst)

    s = s.replace("ç", "ss")
    s = _strip_accents(s)

    s = s.replace("nh", "ny")
    s = s.replace("lh", "li")
    s = s.replace("ch", "sh")
    s = s.replace("rr", "h")

    s = re.sub(r"qu([ei])", r"k\1", s)
    s = re.sub(r"gu([ei])", r"g\1", s)
    s = re.sub(r"(?<=[aeiou])c([ei])", r"ss\1", s)
    s = re.sub(r"c([ei])", r"s\1", s)
    s = re.sub(r"g([ei])", r"j\1", s)
    s = re.sub(r"\br(?=[aeiou])", "h", s)

    s = re.sub(r"\bvoce\b", "vosse", s)
    s = re.sub(r"\bvoces\b", "vosses", s)
    s = re.sub(r"\bmuito\b", "muinto", s)
    s = re.sub(r"\btambem\b", "tanbein", s)
    s = re.sub(r"\bnao\b", "naun", s)

    return " ".join(s.split())


class TextToSpeech:
    def __init__(
        self,
        voice: str = DEFAULT_VOICE_ID,
        enabled: bool = True,
        volume: float = 0.9,
        base_rate_pct: int = 10,
        pitch_hz: int = 15,
        tts_provider: str = DEFAULT_TTS_PROVIDER,
        miku_model: str = DEFAULT_MIKU_MODEL,
        miku_phonetic_ptbr: bool = False,
        miku_timeout_s: float = 28.0,
        miku_f0_up_key: int = 6,
        miku_f0_method: str = "pm",
        on_start: Callable[[], None] | None = None,
        on_end: Callable[[], None] | None = None,
        on_mouth_open: Callable[[float], None] | None = None,
    ) -> None:
        # Remove sufixo '-Female' caso venha no formato da Space ('pt-BR-FranciscaNeural-Female')
        clean_voice = voice[:-7] if voice.endswith("-Female") else voice
        self.voice = clean_voice if clean_voice in AVAILABLE_PT_VOICES.values() else DEFAULT_VOICE_ID
        self.enabled = bool(enabled)
        self.volume = max(0.0, min(1.0, float(volume)))
        self.base_rate_pct = int(base_rate_pct)
        self.pitch_hz = int(pitch_hz)
        self.tts_provider = (
            tts_provider if tts_provider in AVAILABLE_TTS_PROVIDERS.values() else DEFAULT_TTS_PROVIDER
        )
        self.miku_model = (
            miku_model if miku_model in AVAILABLE_MIKU_MODELS.values() else DEFAULT_MIKU_MODEL
        )
        self.miku_phonetic_ptbr = bool(miku_phonetic_ptbr)
        self.miku_timeout_s = max(8.0, min(90.0, float(miku_timeout_s)))
        self.miku_f0_up_key = int(miku_f0_up_key)
        self.miku_f0_method = miku_f0_method if miku_f0_method in {"rmvpe", "pm"} else "pm"

        self.on_start = on_start
        self.on_end = on_end
        self.on_mouth_open = on_mouth_open

        self._stop_event = threading.Event()
        self._play_lock = threading.Lock()
        self._speaking = False

        # Motor RVC 100% local (data/models/miku_rvc/)
        self._local_miku = None
        self._local_miku_lock = threading.Lock()

        # Cliente Gradio da Space John6666/mikuTTS (quando tts_provider == "miku_hf")
        self._miku_client = None
        self._miku_client_lock = threading.Lock()
        self._active_miku_job = None

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def preload_async(self) -> None:
        """Pré-carrega os modelos locais da Miku (`hubert_base.pt`, `rmvpe.pt`, `.pth`) em background."""
        def _task() -> None:
            try:
                eng = self._get_local_miku()
                if eng.is_available():
                    import numpy as np

                    dummy = np.zeros(8000, dtype=np.float32)
                    eng.convert(
                        dummy,
                        model_name=self.miku_model,
                        f0_up_key=self.miku_f0_up_key,
                        f0_method=self.miku_f0_method,
                    )
                    log.info("Modelo RVC local da Miku (%s) pré-aquecido e pronto!", self.miku_model)
            except Exception as exc:
                log.debug("Pré-carregamento do RVC local ignorado: %s", exc)

        threading.Thread(target=_task, daemon=True, name="rin-miku-preload").start()

    def _get_local_miku(self):
        with self._local_miku_lock:
            if self._local_miku is None:
                from src.voice.rvc_infer.local_rvc import LocalMikuEngine

                self._local_miku = LocalMikuEngine()
            return self._local_miku

    def _format_prosody(self, emotion: str) -> tuple[str, str, int, int]:
        """Retorna `(rate_str, pitch_str, rate_int, pitch_int)` sempre como inteiros válidos."""
        mod = EMOTION_MODULATION.get(emotion, EMOTION_MODULATION["neutra"])
        rate_val = int(max(-40, min(60, int(round(self.base_rate_pct)) + int(mod.rate_delta_pct))))
        pitch_val = int(max(-30, min(50, int(round(self.pitch_hz)) + int(mod.pitch_delta_hz))))
        return f"{rate_val:+d}%", f"{pitch_val:+d}Hz", rate_val, pitch_val

    def prepare_speech_pcm(self, text: str, emotion: str = "neutra"):
        """Pré-sintetiza o áudio contínuo enquanto a Rin ainda está no estado 'Pensando'
        para que, assim que o texto aparecer na tela, a voz comece no mesmo milissegundo (0s delay)."""
        if not self.enabled:
            return None
        cleaned = clean_text_for_speech(text)
        if not cleaned:
            return None
        self._stop_event.clear()
        try:
            return self._synthesize_pcm(cleaned, emotion)
        except Exception as exc:
            log.warning("Falha ao pré-sintetizar TTS: %s", exc)
            return None

    def play_prepared_pcm(
        self,
        pcm,
        on_done: Callable[[], None] | None = None,
    ) -> None:
        """Toca imediatamente um buffer PCM já sintetizado (zero delay após o texto aparecer)."""
        if not self.enabled or pcm is None:
            if on_done:
                on_done()
            return
        self.stop()
        self._stop_event.clear()
        threading.Thread(
            target=self._play_prepared_worker,
            args=(pcm, on_done),
            daemon=True,
            name="rin-tts-play",
        ).start()

    def _play_prepared_worker(
        self,
        pcm,
        on_done: Callable[[], None] | None,
    ) -> None:
        with self._play_lock:
            if self._stop_event.is_set():
                if on_done:
                    on_done()
                return
            self._speaking = True
            if self.on_start:
                try:
                    self.on_start()
                except Exception:
                    pass
            try:
                if pcm is not None and not self._stop_event.is_set():
                    self._play_pcm(pcm)
            except Exception as exc:
                log.warning("Falha ao reproduzir TTS da Rin: %s", exc)
            finally:
                self._speaking = False
                if self.on_mouth_open:
                    try:
                        self.on_mouth_open(0.0)
                    except Exception:
                        pass
                if self.on_end:
                    try:
                        self.on_end()
                    except Exception:
                        pass
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

    def speak(
        self,
        text: str,
        emotion: str = "neutra",
        on_done: Callable[[], None] | None = None,
    ) -> None:
        """Sintetiza e reproduz a fala da Rin continuamente sem pausas intermediárias."""
        if not self.enabled:
            if on_done:
                on_done()
            return

        cleaned = clean_text_for_speech(text)
        if not cleaned:
            if on_done:
                on_done()
            return

        self.stop()
        self._stop_event.clear()
        threading.Thread(
            target=self._speak_worker,
            args=(cleaned, emotion, on_done),
            daemon=True,
            name="rin-tts",
        ).start()

    def _speak_worker(
        self,
        text: str,
        emotion: str,
        on_done: Callable[[], None] | None,
    ) -> None:
        with self._play_lock:
            if self._stop_event.is_set():
                if on_done:
                    on_done()
                return
            self._speaking = True
            if self.on_start:
                try:
                    self.on_start()
                except Exception:
                    pass

            try:
                pcm = self._synthesize_pcm(text, emotion)
                if pcm is not None and not self._stop_event.is_set():
                    self._play_pcm(pcm)
            except Exception as exc:
                log.warning("Falha no TTS da Rin: %s", exc)
            finally:
                self._speaking = False
                if self.on_mouth_open:
                    try:
                        self.on_mouth_open(0.0)
                    except Exception:
                        pass
                if self.on_end:
                    try:
                        self.on_end()
                    except Exception:
                        pass
                if on_done:
                    try:
                        on_done()
                    except Exception:
                        pass

    def _resample_to_output(self, data, sr: int):
        import numpy as np

        if sr == TTS_SAMPLE_RATE or data.size == 0:
            return np.clip(data, -1.0, 1.0).astype(np.float32)
        duration = data.size / float(sr)
        target_len = max(1, int(round(duration * TTS_SAMPLE_RATE)))
        old_idx = np.linspace(0.0, 1.0, num=data.size, endpoint=False)
        new_idx = np.linspace(0.0, 1.0, num=target_len, endpoint=False)
        resampled = np.interp(new_idx, old_idx, data).astype(np.float32)
        return np.clip(resampled, -1.0, 1.0).astype(np.float32)

    def _synthesize_miku_local_pcm(self, text: str, emotion: str):
        """Executa o pipeline completo do `John6666/mikuTTS` localmente na máquina do usuário:
        1. Gera a voz base (`pt-BR-FranciscaNeural` ou `ja-JP-NanamiNeural` se fonético ativo) via `edge-tts`
           com `rate=f"{rate_int:+d}%"` (inteiros exatos), `volume="+0%"`, `pitch="+0Hz"`.
        2. Decodifica em 16kHz mono float32.
        3. Passa pelo `LocalMikuEngine` (`hubert_base.pt` + `rmvpe.pt` + `1a_miku_default_rvc_(aple)`).
        """
        import av
        import edge_tts
        import numpy as np

        rate_str, _pitch_str, _rate_val, _pitch_val = self._format_prosody(emotion)

        if self.miku_phonetic_ptbr:
            tts_text = ptbr_to_vocaloid_phonetic(text)
            edge_voice = "ja-JP-NanamiNeural"
        else:
            tts_text = text
            # No site John6666/mikuTTS, para PT-BR é usado pt-BR-FranciscaNeural-Female
            edge_voice = "pt-BR-FranciscaNeural"

        async def _fetch_mp3() -> bytes:
            comm = edge_tts.Communicate(
                tts_text,
                voice=edge_voice,
                rate=rate_str,
                volume="+0%",
                pitch="+0Hz",
            )
            buf = bytearray()
            async for chunk in comm.stream():
                if self._stop_event.is_set():
                    return b""
                if chunk.get("type") == "audio":
                    buf.extend(chunk["data"])
            return bytes(buf)

        mp3_bytes = asyncio.run(_fetch_mp3())
        if not mp3_bytes or self._stop_event.is_set():
            return None

        # Decodifica para 16000 Hz mono float32 (taxa de entrada do HuBERT/RMVPE no mikuTTS)
        container = av.open(io.BytesIO(mp3_bytes))
        resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        frames = []
        for frame in container.decode(audio=0):
            if self._stop_event.is_set():
                return None
            for rf in resampler.resample(frame):
                frames.append(rf.to_ndarray().reshape(-1))

        if not frames or self._stop_event.is_set():
            return None

        audio_16k = np.concatenate(frames).astype(np.float32) / 32768.0
        # Remove o silêncio inicial/final adicionado pelo edge-tts (~300ms) para resposta imediata
        active_idx = np.where(np.abs(audio_16k) > 0.004)[0]
        if active_idx.size > 0:
            margin = 320  # 20ms de margem suave em 16kHz
            start_i = max(0, int(active_idx[0]) - margin)
            end_i = min(audio_16k.size, int(active_idx[-1]) + margin)
            audio_16k = audio_16k[start_i:end_i]

        eng = self._get_local_miku()
        rvc_audio, tgt_sr = eng.convert(
            audio_16k,
            model_name=self.miku_model,
            f0_up_key=self.miku_f0_up_key,
            f0_method=self.miku_f0_method,
            index_rate=0.75,
            protect=0.33,
        )
        if self._stop_event.is_set():
            return None
        return self._resample_to_output(rvc_audio, tgt_sr)

    def _get_miku_client(self):
        with self._miku_client_lock:
            if self._miku_client is None:
                from gradio_client import Client

                log.info("Conectando ao Space Hugging Face '%s'...", MIKU_SPACE_ID)
                self._miku_client = Client(MIKU_SPACE_ID, verbose=False)
            return self._miku_client

    def _synthesize_miku_hf_pcm(self, text: str, emotion: str):
        """Sintetiza via Space `John6666/mikuTTS` (endpoint `/tts`) com `speed` inteiro e `pt-BR-FranciscaNeural-Female`."""
        import numpy as np
        import soundfile as sf

        _rate_str, _pitch_str, rate_val, _pitch_val = self._format_prosody(emotion)
        # No app.py da Space: speed é um gr.Slider(step=10) formatado como f"+{speed}%".
        # Deve ser enviado como int (ex: 10, nunca 15.0) para que o edge-tts remoto não lance ValueError!
        speed_int = int(round(rate_val / 10.0) * 10)

        if self.miku_phonetic_ptbr:
            tts_text = ptbr_to_vocaloid_phonetic(text)
            speaker_voice = MIKU_JA_SPEAKER
        else:
            tts_text = text
            speaker_voice = MIKU_PTBR_SPEAKER  # "pt-BR-FranciscaNeural-Female"

        client = self._get_miku_client()
        if self._stop_event.is_set():
            return None

        job = client.submit(
            self.miku_model,          # param_0: Select a model
            int(speed_int),           # param_1: Voice speed (int! evita '+15.0%')
            0,                        # param_2: Voice volume (int!)
            0,                        # param_3: Voice pitch (int!)
            tts_text,                 # param_4: Text to speak
            speaker_voice,            # param_5: 'pt-BR-FranciscaNeural-Female'
            int(self.miku_f0_up_key), # param_6: Pitch Up key (6 no site para PT-BR)
            "pm",                     # param_7: Pitch extraction algorithm
            0.75,                     # param_8: Index rate
            0.33,                     # param_9: Protect
            api_name=MIKU_API_NAME,
        )
        self._active_miku_job = job
        try:
            result = job.result(timeout=self.miku_timeout_s)
        except Exception:
            try:
                job.cancel()
            except Exception:
                pass
            raise
        finally:
            self._active_miku_job = None

        if self._stop_event.is_set() or not result or len(result) < 3:
            return None

        rvc_wav_path = result[2] or result[1]
        if not rvc_wav_path or not Path(rvc_wav_path).is_file():
            raise RuntimeError(f"mikuTTS não retornou arquivo de áudio válido (info={result[0]!r})")

        try:
            data, sr = sf.read(rvc_wav_path, dtype="float32", always_2d=False)
        finally:
            try:
                os.remove(rvc_wav_path)
            except OSError:
                pass

        if data.ndim > 1:
            data = np.mean(data, axis=1)

        return self._resample_to_output(data, sr)

    def _synthesize_edge_pcm(self, text: str, emotion: str, force_fallback_voice: bool = False):
        """Sintetiza via `edge-tts` puro (sem pedalboard), com `pitch='+15Hz'`."""
        import av
        import edge_tts
        import numpy as np

        rate_str, pitch_str, _rate_val, _pitch_val = self._format_prosody(emotion)
        if force_fallback_voice:
            pitch_str = "+15Hz"

        preferred = "pt-BR-FranciscaNeural" if force_fallback_voice else self.voice
        candidates = [preferred] + [v for v in _EDGE_FALLBACK_CHAIN if v != preferred]

        mp3_bytes = b""
        last_exc: Exception | None = None
        for candidate_voice in candidates:
            if self._stop_event.is_set():
                return None

            async def _fetch_mp3(v_id: str) -> bytes:
                comm = edge_tts.Communicate(text, voice=v_id, rate=rate_str, pitch=pitch_str)
                buf = bytearray()
                async for chunk in comm.stream():
                    if self._stop_event.is_set():
                        return b""
                    if chunk.get("type") == "audio":
                        buf.extend(chunk["data"])
                return bytes(buf)

            try:
                mp3_bytes = asyncio.run(_fetch_mp3(candidate_voice))
                if mp3_bytes:
                    break
            except Exception as exc:
                last_exc = exc
                log.debug(
                    "Voz Edge-TTS '%s' indisponível (%s), tentando próxima da cadeia...",
                    candidate_voice,
                    exc,
                )

        if not mp3_bytes or self._stop_event.is_set():
            if last_exc:
                raise last_exc
            return None

        container = av.open(io.BytesIO(mp3_bytes))
        resampler = av.AudioResampler(format="s16", layout="mono", rate=TTS_SAMPLE_RATE)
        frames = []
        for frame in container.decode(audio=0):
            if self._stop_event.is_set():
                return None
            for rf in resampler.resample(frame):
                frames.append(rf.to_ndarray().reshape(-1))

        if not frames or self._stop_event.is_set():
            return None

        return np.concatenate(frames).astype(np.float32) / 32768.0

    def _synthesize_pcm(self, text: str, emotion: str):
        import numpy as np

        pcm = None
        if self.tts_provider == "miku_local":
            try:
                pcm = self._synthesize_miku_local_pcm(text, emotion)
            except Exception as exc:
                log.warning(
                    "[TTS] Motor Miku RVC Local falhou (%s). "
                    "Usando fallback automático edge-tts (pt-BR-FranciscaNeural, pitch='+15Hz').",
                    exc,
                )
                pcm = self._synthesize_edge_pcm(text, emotion, force_fallback_voice=True)
        elif self.tts_provider == "miku_hf":
            try:
                pcm = self._synthesize_miku_hf_pcm(text, emotion)
            except Exception as exc:
                log.warning(
                    "[TTS] Space John6666/mikuTTS indisponível ou em timeout (%s). "
                    "Acionando Miku RVC Local / Fallback edge-tts (+15Hz).",
                    exc,
                )
                try:
                    if self._get_local_miku().is_available():
                        pcm = self._synthesize_miku_local_pcm(text, emotion)
                    else:
                        pcm = self._synthesize_edge_pcm(text, emotion, force_fallback_voice=True)
                except Exception:
                    pcm = self._synthesize_edge_pcm(text, emotion, force_fallback_voice=True)
        else:
            pcm = self._synthesize_edge_pcm(text, emotion, force_fallback_voice=False)

        if pcm is None or self._stop_event.is_set():
            return None

        if self.volume != 1.0:
            pcm = np.clip(pcm * self.volume, -1.0, 1.0)
        return pcm

    def _play_pcm(self, pcm) -> None:
        import numpy as np
        import sounddevice as sd

        chunk_samples = max(1, int(TTS_SAMPLE_RATE / 60))  # blocos de ~16.6ms (60 FPS LipSync)
        total = len(pcm)
        pos = 0

        with sd.OutputStream(samplerate=TTS_SAMPLE_RATE, channels=1, dtype="float32") as out:
            while pos < total and not self._stop_event.is_set():
                end = min(total, pos + chunk_samples)
                block = pcm[pos:end]
                if self.on_mouth_open and block.size:
                    rms = float(np.sqrt(np.mean(block * block)))
                    mouth = min(1.0, rms * 4.8)
                    try:
                        self.on_mouth_open(mouth)
                    except Exception:
                        pass
                out.write(block.reshape(-1, 1))
                pos = end

    def stop(self) -> None:
        """Interrompe a fala e cancela qualquer requisição pendente ao mikuTTS imediatamente."""
        self._stop_event.set()
        if self.on_mouth_open:
            try:
                self.on_mouth_open(0.0)
            except Exception:
                pass
        job = self._active_miku_job
        if job is not None:
            try:
                job.cancel()
            except Exception:
                pass
