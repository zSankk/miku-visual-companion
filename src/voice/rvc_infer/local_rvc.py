"""Motor RVC 100% Local da Hatsune Miku (baseado em `John6666/mikuTTS` & `NoCrypt/miku_RVC`).

Executa localmente na máquina do usuário:
1. Extração de features ContentVec/HuBERT (`data/models/miku_rvc/hubert_base.pt`) via `torchaudio` nativo.
2. Extração de pitch F0 (`pm` via `praat-parselmouth` ou `rmvpe` via `data/models/miku_rvc/rmvpe.pt`).
3. Busca vetorial FAISS (`*.index`) + síntese neural VITS/NSF (`*.pth` de `NoCrypt/miku_RVC`).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import pickle
import threading
import time
import warnings

warnings.filterwarnings("ignore", category=FutureWarning, module="torch")

import faiss
import numpy as np
import parselmouth
from scipy import signal
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from torchaudio.models.wav2vec2.utils.import_fairseq import _convert_state_dict

from src.voice.rvc_infer.models import (
    SynthesizerTrnMs256NSFsid,
    SynthesizerTrnMs256NSFsid_nono,
    SynthesizerTrnMs768NSFsid,
    SynthesizerTrnMs768NSFsid_nono,
)
from src.voice.rvc_infer.rmvpe import RMVPE

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
MIKU_MODELS_DIR = PROJECT_ROOT / "data" / "models" / "miku_rvc"

# Filtro passa-alta Butterworth 48Hz em 16kHz (idêntico ao vc_infer_pipeline.py do mikuTTS)
_BH, _AH = signal.butter(N=5, Wn=48, btype="high", fs=16000)


class _FairseqDummy:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def __setstate__(self, state) -> None:
        pass


class _FairseqBypassUnpickler(pickle.Unpickler):
    """Permite carregar `hubert_base.pt` do Fairseq diretamente no PyTorch/Torchaudio em Python 3.12."""

    def find_class(self, module: str, name: str):
        if module.startswith(("fairseq", "omegaconf")):
            return _FairseqDummy
        return super().find_class(module, name)


_PICKLE_MODULE = type(
    "_FairseqPickleModule",
    (),
    {
        "Unpickler": _FairseqBypassUnpickler,
        "load": staticmethod(lambda f, **kw: _FairseqBypassUnpickler(f).load()),
    },
)


class LocalHubertWrapper(nn.Module):
    """Wrapper compatível com a interface `hubert_model.extract_features` + `final_proj` do mikuTTS."""

    def __init__(self, hubert_pt_path: Path, device: str = "cpu") -> None:
        super().__init__()
        ckpt = torch.load(
            str(hubert_pt_path),
            map_location="cpu",
            weights_only=False,
            pickle_module=_PICKLE_MODULE,
        )
        sd = ckpt["model"]
        self.backbone = torchaudio.models.hubert_base()
        converted = _convert_state_dict(sd)
        converted.pop("label_embs_concat", None)
        self.backbone.load_state_dict(converted, strict=True)
        self.backbone.eval()

        self.final_proj = nn.Linear(768, 256)
        if "final_proj.weight" in sd and "final_proj.bias" in sd:
            self.final_proj.weight.data.copy_(sd["final_proj.weight"])
            self.final_proj.bias.data.copy_(sd["final_proj.bias"])
        self.final_proj.eval()
        self.to(device)

    @torch.no_grad()
    def extract_features(self, source: torch.Tensor, padding_mask=None, output_layer: int = 12):
        feats_list, _ = self.backbone.extract_features(source, num_layers=output_layer)
        return (feats_list[-1],)


def _compute_rms(y: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    """Equivalente leve a `librosa.feature.rms` sem depender do pacote librosa."""
    pad = frame_length // 2
    y_pad = np.pad(y, (pad, pad), mode="constant")
    n_frames = 1 + max(0, (len(y_pad) - frame_length) // hop_length)
    rms = np.empty((1, n_frames), dtype=np.float32)
    for i in range(n_frames):
        start = i * hop_length
        frame = y_pad[start : start + frame_length]
        rms[0, i] = np.sqrt(np.mean(frame * frame) + 1e-8)
    return rms


def _change_rms(data1: np.ndarray, sr1: int, data2: np.ndarray, sr2: int, rate: float) -> np.ndarray:
    rms1 = _compute_rms(data1, sr1 // 2 * 2, sr1 // 2)
    rms2 = _compute_rms(data2, sr2 // 2 * 2, sr2 // 2)
    t_rms1 = F.interpolate(
        torch.from_numpy(rms1).unsqueeze(0), size=data2.shape[0], mode="linear"
    ).squeeze()
    t_rms2 = F.interpolate(
        torch.from_numpy(rms2).unsqueeze(0), size=data2.shape[0], mode="linear"
    ).squeeze()
    t_rms2 = torch.max(t_rms2, torch.zeros_like(t_rms2) + 1e-6)
    gain = (torch.pow(t_rms1, 1.0 - rate) * torch.pow(t_rms2, rate - 1.0)).numpy()
    return data2 * gain


class LocalRVCConverter:
    """Pipeline de conversão de voz RVC local idêntico ao `VC` de `John6666/mikuTTS`."""

    def __init__(self, tgt_sr: int, device: str = "cpu") -> None:
        self.device = device
        self.is_half = False
        self.sr = 16000
        self.window = 160
        # 12 frames (0.12s) de padding por lado em vez de 1.0s inteiro:
        # mantém alinhamento exato de janelas (10ms) reduzindo a latência pela metade.
        pad_frames = 12
        self.x_pad = pad_frames / 100.0
        self.x_query = 6
        self.x_center = 38
        self.x_max = 41
        self.t_pad = self.window * pad_frames
        self.t_pad_tgt = (tgt_sr // 100) * pad_frames
        self.t_pad2 = self.t_pad * 2
        self.t_query = self.sr * self.x_query
        self.t_center = self.sr * self.x_center
        self.t_max = self.sr * self.x_max
        self.model_rmvpe: RMVPE | None = None

    def get_f0(self, x: np.ndarray, p_len: int, f0_up_key: int, f0_method: str):
        time_step = self.window / self.sr * 1000.0
        f0_min = 50.0
        f0_max = 1100.0
        f0_mel_min = 1127.0 * np.log(1.0 + f0_min / 700.0)
        f0_mel_max = 1127.0 * np.log(1.0 + f0_max / 700.0)

        if f0_method == "rmvpe" and self.model_rmvpe is not None:
            f0 = self.model_rmvpe.infer_from_audio(x, thred=0.03)
        else:
            f0 = (
                parselmouth.Sound(x, self.sr)
                .to_pitch_ac(
                    time_step=time_step / 1000.0,
                    voicing_threshold=0.6,
                    pitch_floor=f0_min,
                    pitch_ceiling=f0_max,
                )
                .selected_array["frequency"]
            )
            pad_size = (p_len - len(f0) + 1) // 2
            if pad_size > 0 or p_len - len(f0) - pad_size > 0:
                f0 = np.pad(f0, [[pad_size, p_len - len(f0) - pad_size]], mode="constant")

        f0 = f0 * pow(2.0, f0_up_key / 12.0)
        f0bak = f0.copy()
        f0_mel = 1127.0 * np.log(1.0 + f0 / 700.0)
        f0_mel[f0_mel > 0] = (f0_mel[f0_mel > 0] - f0_mel_min) * 254.0 / (
            f0_mel_max - f0_mel_min
        ) + 1.0
        f0_mel[f0_mel <= 1] = 1
        f0_mel[f0_mel > 255] = 255
        f0_coarse = np.rint(f0_mel).astype(np.int32)
        return f0_coarse, f0bak

    def _vc_chunk(
        self,
        hubert_model: LocalHubertWrapper,
        net_g,
        sid: torch.Tensor,
        audio0: np.ndarray,
        pitch: torch.Tensor | None,
        pitchf: torch.Tensor | None,
        index,
        big_npy: np.ndarray | None,
        index_rate: float,
        version: str,
        protect: float,
    ) -> np.ndarray:
        feats = torch.from_numpy(audio0).float()
        if feats.dim() == 2:
            feats = feats.mean(-1)
        feats = feats.view(1, -1).to(self.device)

        with torch.no_grad():
            logits = hubert_model.extract_features(
                source=feats,
                output_layer=9 if version == "v1" else 12,
            )
            feats = hubert_model.final_proj(logits[0]) if version == "v1" else logits[0]

        if protect < 0.5 and pitch is not None and pitchf is not None:
            feats0 = feats.clone()

        if index is not None and big_npy is not None and index_rate != 0:
            npy = feats[0].cpu().numpy().astype("float32")
            score, ix = index.search(npy, k=8)
            weight = np.square(1.0 / np.maximum(score, 1e-6))
            weight /= weight.sum(axis=1, keepdims=True)
            npy = np.sum(big_npy[ix] * np.expand_dims(weight, axis=2), axis=1)
            feats = (
                torch.from_numpy(npy).unsqueeze(0).to(self.device) * index_rate
                + (1.0 - index_rate) * feats
            )

        feats = F.interpolate(feats.permute(0, 2, 1), scale_factor=2).permute(0, 2, 1)
        if protect < 0.5 and pitch is not None and pitchf is not None:
            feats0 = F.interpolate(feats0.permute(0, 2, 1), scale_factor=2).permute(0, 2, 1)

        p_len = audio0.shape[0] // self.window
        if feats.shape[1] < p_len:
            p_len = feats.shape[1]
            if pitch is not None and pitchf is not None:
                pitch = pitch[:, :p_len]
                pitchf = pitchf[:, :p_len]

        if protect < 0.5 and pitch is not None and pitchf is not None:
            pitchff = pitchf.clone()
            pitchff[pitchf > 0] = 1
            pitchff[pitchf < 1] = protect
            pitchff = pitchff.unsqueeze(-1)
            feats = feats * pitchff + feats0 * (1.0 - pitchff)
            feats = feats.to(feats0.dtype)

        p_len_t = torch.tensor([p_len], device=self.device).long()
        with torch.no_grad():
            if pitch is not None and pitchf is not None:
                audio1 = (
                    net_g.infer(feats, p_len_t, pitch, pitchf, sid)[0][0, 0]
                    .data.cpu()
                    .float()
                    .numpy()
                )
            else:
                audio1 = (
                    net_g.infer(feats, p_len_t, sid)[0][0, 0]
                    .data.cpu()
                    .float()
                    .numpy()
                )
        return audio1

    def pipeline(
        self,
        hubert_model: LocalHubertWrapper,
        net_g,
        audio: np.ndarray,
        f0_up_key: int,
        f0_method: str,
        file_index: str,
        index_rate: float,
        if_f0: int,
        tgt_sr: int,
        rms_mix_rate: float,
        version: str,
        protect: float,
         preloaded_index=None,
        preloaded_big_npy=None,
    ) -> np.ndarray:
        index = preloaded_index
        big_npy = preloaded_big_npy
        if index is None and file_index and os.path.exists(file_index) and index_rate != 0:
            try:
                index = faiss.read_index(file_index)
                big_npy = index.reconstruct_n(0, index.ntotal)
            except Exception as exc:
                log.warning("Falha ao ler índice FAISS (%s): %s", file_index, exc)
                index = big_npy = None

        audio = signal.filtfilt(_BH, _AH, audio).astype(np.float32)
        audio_pad = np.pad(audio, (self.window // 2, self.window // 2), mode="reflect")
        opt_ts = []
        if audio_pad.shape[0] > self.t_max:
            audio_sum = np.zeros_like(audio)
            for i in range(self.window):
                audio_sum += audio_pad[i : i - self.window]
            for t in range(self.t_center, audio.shape[0], self.t_center):
                opt_ts.append(
                    t
                    - self.t_query
                    + np.where(
                        np.abs(audio_sum[t - self.t_query : t + self.t_query])
                        == np.abs(audio_sum[t - self.t_query : t + self.t_query]).min()
                    )[0][0]
                )

        s = 0
        audio_opt = []
        t = None
        audio_pad = np.pad(audio, (self.t_pad, self.t_pad), mode="reflect")
        p_len = audio_pad.shape[0] // self.window
        sid = torch.tensor(0, device=self.device).unsqueeze(0).long()

        pitch, pitchf = None, None
        if if_f0 == 1:
            p_coarse, p_bak = self.get_f0(audio_pad, p_len, f0_up_key, f0_method)
            p_coarse = p_coarse[:p_len]
            p_bak = p_bak[:p_len]
            pitch = torch.tensor(p_coarse, device=self.device).unsqueeze(0).long()
            pitchf = torch.tensor(p_bak, device=self.device).unsqueeze(0).float()

        for t in opt_ts:
            t = t // self.window * self.window
            chunk = self._vc_chunk(
                hubert_model,
                net_g,
                sid,
                audio_pad[s : t + self.t_pad2 + self.window],
                pitch[:, s // self.window : (t + self.t_pad2) // self.window] if if_f0 == 1 else None,
                pitchf[:, s // self.window : (t + self.t_pad2) // self.window] if if_f0 == 1 else None,
                index,
                big_npy,
                index_rate,
                version,
                protect,
            )[self.t_pad_tgt : -self.t_pad_tgt]
            audio_opt.append(chunk)
            s = t

        tail = self._vc_chunk(
            hubert_model,
            net_g,
            sid,
            audio_pad[t:],
            (pitch[:, t // self.window :] if t is not None else pitch) if if_f0 == 1 else None,
            (pitchf[:, t // self.window :] if t is not None else pitchf) if if_f0 == 1 else None,
            index,
            big_npy,
            index_rate,
            version,
            protect,
        )[self.t_pad_tgt : -self.t_pad_tgt]
        audio_opt.append(tail)

        out = np.concatenate(audio_opt).astype(np.float32)
        if rms_mix_rate != 1.0:
            out = _change_rms(audio, 16000, out, tgt_sr, rms_mix_rate)
        audio_max = float(np.abs(out).max()) / 0.99
        if audio_max > 1.0:
            out = out / audio_max
        return out.astype(np.float32)


class LocalMikuEngine:
    """Gerencia o carregamento único e em cache dos modelos locais da Hatsune Miku."""

    def __init__(self, models_dir: Path = MIKU_MODELS_DIR) -> None:
        self.models_dir = models_dir
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self._lock = threading.Lock()
        self._hubert: LocalHubertWrapper | None = None
        self._rmvpe: RMVPE | None = None
        self._loaded_models: dict[str, tuple] = {}

    def is_available(self) -> bool:
        return (self.models_dir / "hubert_base.pt").is_file()

    def _ensure_model_downloaded(self, model_name: str) -> Path:
        model_dir = self.models_dir / model_name
        if model_dir.is_dir() and any(model_dir.glob("*.pth")):
            return model_dir

        # Se o usuário escolher outro modelo do NoCrypt/miku_RVC na UI, baixa automaticamente
        from huggingface_hub import hf_hub_download, list_repo_files

        log.info("Baixando modelo RVC '%s' de NoCrypt/miku_RVC para uso local...", model_name)
        files = [
            f
            for f in list_repo_files("NoCrypt/miku_RVC")
            if f.startswith(f"{model_name}/") and f.endswith((".pth", ".index"))
        ]
        if not files:
            raise FileNotFoundError(f"Modelo RVC '{model_name}' não encontrado em NoCrypt/miku_RVC")
        model_dir.mkdir(parents=True, exist_ok=True)
        for rel in files:
            cached = Path(hf_hub_download("NoCrypt/miku_RVC", rel))
            dst = self.models_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.is_file():
                import shutil

                shutil.copy2(cached, dst)
        return model_dir

    def _load_model_bundle(self, model_name: str):
        if model_name in self._loaded_models:
            return self._loaded_models[model_name]

        model_dir = self._ensure_model_downloaded(model_name)
        pth_files = list(model_dir.glob("*.pth"))
        if not pth_files:
            raise FileNotFoundError(f"Nenhum arquivo .pth em {model_dir}")
        pth_path = pth_files[0]

        log.info("Carregando checkpoint RVC local da Miku: %s", pth_path.name)
        cpt = torch.load(str(pth_path), map_location="cpu", weights_only=False)
        tgt_sr = int(cpt["config"][-1])
        cpt["config"][-3] = cpt["weight"]["emb_g.weight"].shape[0]
        if_f0 = int(cpt.get("f0", 1))
        version = str(cpt.get("version", "v1"))

        if version == "v1":
            if if_f0 == 1:
                net_g = SynthesizerTrnMs256NSFsid(*cpt["config"], is_half=False)
            else:
                net_g = SynthesizerTrnMs256NSFsid_nono(*cpt["config"])
        elif version == "v2":
            if if_f0 == 1:
                net_g = SynthesizerTrnMs768NSFsid(*cpt["config"], is_half=False)
            else:
                net_g = SynthesizerTrnMs768NSFsid_nono(*cpt["config"])
        else:
            raise ValueError(f"Versão de modelo RVC desconhecida: {version}")

        del net_g.enc_q
        net_g.load_state_dict(cpt["weight"], strict=False)
        net_g.eval().to(self.device).float()

        vc = LocalRVCConverter(tgt_sr=tgt_sr, device=self.device)
        index_files = list(model_dir.glob("*.index"))
        index_file = str(index_files[0]) if index_files else ""
        pre_index = None
        pre_big_npy = None
        if index_file:
            try:
                pre_index = faiss.read_index(index_file)
                pre_big_npy = pre_index.reconstruct_n(0, pre_index.ntotal)
            except Exception as exc:
                log.warning("Não foi possível pré-carregar índice FAISS (%s): %s", index_file, exc)

        bundle = (tgt_sr, net_g, vc, version, index_file, if_f0, pre_index, pre_big_npy)
        self._loaded_models[model_name] = bundle
        return bundle

    def convert(
        self,
        audio_16k: np.ndarray,
        model_name: str = "1a_miku_default_rvc_(aple)",
        f0_up_key: int = 6,
        f0_method: str = "pm",
        index_rate: float = 0.75,
        protect: float = 0.33,
    ) -> tuple[np.ndarray, int]:
        """Converte um vetor de áudio mono 16kHz float32 na voz da Miku RVC localmente."""
        with self._lock:
            t0 = time.monotonic()
            if self._hubert is None:
                hubert_path = self.models_dir / "hubert_base.pt"
                log.info("Carregando modelo base ContentVec/HuBERT local (%s)...", hubert_path.name)
                self._hubert = LocalHubertWrapper(hubert_path, device=self.device)

            tgt_sr, net_g, vc, version, index_file, if_f0, pre_index, pre_big_npy = (
                self._load_model_bundle(model_name)
            )

            if f0_method == "rmvpe":
                if self._rmvpe is None:
                    rmvpe_path = self.models_dir / "rmvpe.pt"
                    log.info("Carregando extrator de pitch RMVPE local (%s)...", rmvpe_path.name)
                    self._rmvpe = RMVPE(str(rmvpe_path), is_half=False, device=self.device)
                vc.model_rmvpe = self._rmvpe

            out_pcm = vc.pipeline(
                hubert_model=self._hubert,
                net_g=net_g,
                audio=audio_16k,
                f0_up_key=int(f0_up_key),
                f0_method=f0_method,
                file_index=index_file,
                index_rate=float(index_rate),
                if_f0=if_f0,
                tgt_sr=tgt_sr,
                rms_mix_rate=0.25,
                version=version,
                protect=float(protect),
                preloaded_index=pre_index,
                preloaded_big_npy=pre_big_npy,
            )
            log.info(
                "[Miku RVC Local] Áudio sintetizado em %.2fs (modelo=%s, f0=%s, sr=%dHz)",
                time.monotonic() - t0,
                model_name,
                f0_method,
                tgt_sr,
            )
            return out_pcm, tgt_sr
