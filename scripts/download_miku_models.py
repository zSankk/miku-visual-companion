"""Baixa e instala localmente os pesos do modelo RVC da Hatsune Miku (NoCrypt/mikuTTS / NoCrypt/miku_RVC).

Baixa SOMENTE pesos (nenhum código `.py`): o código de inferência já está versionado em
`src/voice/rvc_infer/`. Todos os downloads usam revisão fixa e são conferidos por SHA-256,
pois os checkpoints são carregados com `torch.load` (pickle).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
sys.stdout.reconfigure(encoding="utf-8")

from huggingface_hub import hf_hub_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIKU_DIR = PROJECT_ROOT / "data" / "models" / "miku_rvc"

NOCRYPT_SPACE_REPO = "NoCrypt/mikuTTS"
NOCRYPT_SPACE_REV = "28cf14cedf36710419d2a868ddb038f45bc8c7cd"
NOCRYPT_ASSETS = {
    "hubert_base.pt": "f54b40fd2802423a5643779c4861af1e9ee9c1564dc9d32f54f20b5ffba7db96",
    "rmvpe.pt": "a5ed4719f59085d1affc5d81354c70828c740584f2d24e782523345a6a278962",
}

MIKU_RVC_REPO = "NoCrypt/miku_RVC"
MIKU_RVC_REV = "eb9b8df98fde23f2d913977c95e23095e9164ed4"
MIKU_MODEL_FILES = {
    "1a_miku_default_rvc_(aple)/miku_default_rvc.pth": (
        "64b45881093dc68e41ebd0e0344f6c41056026ede3f6074375375c849291e2d3"
    ),
    "1a_miku_default_rvc_(aple)/added_IVF4457_Flat_nprobe_1_miku_default_rvc_v2.index": (
        "abb6f0648337bef18addef0171745306f2ece1f74841fcdfa38272adb1bc6e98"
    ),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(repo: str, rel: str, revision: str, expected_sha: str, repo_type: str | None = None) -> None:
    dst = MIKU_DIR / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_file() and _sha256(dst) == expected_sha:
        print(f"   -> {rel} já existe localmente ({dst.stat().st_size // (1024*1024)} MB)")
        return

    src = Path(hf_hub_download(repo, rel, repo_type=repo_type, revision=revision))
    actual_sha = _sha256(src)
    if actual_sha != expected_sha:
        raise RuntimeError(
            f"SHA-256 inesperado para {rel}: {actual_sha} (esperado {expected_sha}). "
            "Arquivo NÃO instalado."
        )
    shutil.copy2(src, dst)
    print(f"   -> {dst.relative_to(PROJECT_ROOT)} ({dst.stat().st_size // (1024*1024)} MB)")


def download_all() -> None:
    MIKU_DIR.mkdir(parents=True, exist_ok=True)

    print("1. Baixando pesos base (hubert_base.pt e rmvpe.pt)...")
    for asset, sha in NOCRYPT_ASSETS.items():
        _fetch(NOCRYPT_SPACE_REPO, asset, NOCRYPT_SPACE_REV, sha, repo_type="space")

    print("2. Baixando modelo RVC da Hatsune Miku (1a_miku_default_rvc_(aple))...")
    for mfile, sha in MIKU_MODEL_FILES.items():
        _fetch(MIKU_RVC_REPO, mfile, MIKU_RVC_REV, sha)

    print("Concluído com sucesso!")


if __name__ == "__main__":
    download_all()
