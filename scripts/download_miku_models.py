"""Baixa e instala localmente o modelo RVC da Hatsune Miku (John6666/mikuTTS / NoCrypt/miku_RVC)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
sys.stdout.reconfigure(encoding="utf-8")

from huggingface_hub import hf_hub_download

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIKU_DIR = PROJECT_ROOT / "data" / "models" / "miku_rvc"
INFER_PACK_DIR = PROJECT_ROOT / "src" / "voice" / "rvc_infer"

SPACE_CODE_FILES = [
    "lib/infer_pack/attentions.py",
    "lib/infer_pack/commons.py",
    "lib/infer_pack/models.py",
    "lib/infer_pack/modules.py",
    "lib/infer_pack/transforms.py",
    "rmvpe.py",
]

NOCRYPT_SPACE_REPO = "NoCrypt/mikuTTS"
NOCRYPT_SPACE_REV = "28cf14cedf36710419d2a868ddb038f45bc8c7cd"
NOCRYPT_ASSETS = ["hubert_base.pt", "rmvpe.pt"]

MIKU_RVC_REPO = "NoCrypt/miku_RVC"
MIKU_MODEL_FILES = [
    "1a_miku_default_rvc_(aple)/miku_default_rvc.pth",
    "1a_miku_default_rvc_(aple)/added_IVF4457_Flat_nprobe_1_miku_default_rvc_v2.index",
]


def download_all() -> None:
    MIKU_DIR.mkdir(parents=True, exist_ok=True)
    INFER_PACK_DIR.mkdir(parents=True, exist_ok=True)

    print("1. Baixando arquitetura RVC de John6666/mikuTTS...")
    for rel in SPACE_CODE_FILES:
        src = Path(hf_hub_download("John6666/mikuTTS", rel, repo_type="space"))
        dst = INFER_PACK_DIR / Path(rel).name
        shutil.copy2(src, dst)
        print(f"   -> {dst.relative_to(PROJECT_ROOT)}")

    print("2. Baixando pesos base (hubert_base.pt e rmvpe.pt)...")
    for asset in NOCRYPT_ASSETS:
        dst = MIKU_DIR / asset
        if dst.is_file() and dst.stat().st_size > 1_000_000:
            print(f"   -> {asset} já existe localmente ({dst.stat().st_size // (1024*1024)} MB)")
            continue
        src = Path(
            hf_hub_download(
                NOCRYPT_SPACE_REPO,
                asset,
                repo_type="space",
                revision=NOCRYPT_SPACE_REV,
            )
        )
        shutil.copy2(src, dst)
        print(f"   -> {dst.relative_to(PROJECT_ROOT)} ({dst.stat().st_size // (1024*1024)} MB)")

    print("3. Baixando modelo RVC da Hatsune Miku (1a_miku_default_rvc_(aple))...")
    for mfile in MIKU_MODEL_FILES:
        dst = MIKU_DIR / mfile
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_file() and dst.stat().st_size > 100_000:
            print(f"   -> {mfile} já existe localmente ({dst.stat().st_size // (1024*1024)} MB)")
            continue
        src = Path(hf_hub_download(MIKU_RVC_REPO, mfile))
        shutil.copy2(src, dst)
        print(f"   -> {dst.relative_to(PROJECT_ROOT)} ({dst.stat().st_size // (1024*1024)} MB)")

    print("Concluído com sucesso!")


if __name__ == "__main__":
    download_all()
