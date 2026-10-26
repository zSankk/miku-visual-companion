"""Baixa e configura os modelos Live2D da Hatsune Miku do Projeto Sekai (Cubism 4) + Motions Oficiais."""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WEB_LIB_DIR = PROJECT_ROOT / "src" / "avatar" / "web" / "lib"
MODELS_DIR = PROJECT_ROOT / "assets" / "models"

SEKAI_STORAGE = "https://storage.sekai.best/sekai-live2d-assets/"

# 4 Modelos Oficiais Cubism 4 da Hatsune Miku do Project Sekai!
SEKAI_MIKU_MODELS = [
    {
        "slug": "miku_sekai_normal",
        "title": "Hatsune Miku · Projeto Sekai (Original 3.0)",
        "modelPath": "v2/main/21_miku/v2_21miku_normal",
        "modelFile": "21miku_normal_3.0_f_t06.model3.json",
    },
    {
        "slug": "miku_sekai_night",
        "title": "Hatsune Miku · Nightcord at 25:00 (Sekai)",
        "modelPath": "v2/main/21_miku/v2_21miku_night",
        "modelFile": "v2_21miku_night_t01.model3.json",
    },
    {
        "slug": "miku_sekai_idol",
        "title": "Hatsune Miku · More More Jump! Idol (Sekai)",
        "modelPath": "v2/main/21_miku/v2_21miku_idol",
        "modelFile": "21miku_morejump2_t02.model3.json",
    },
    {
        "slug": "miku_sekai_wonder",
        "title": "Hatsune Miku · Wonderlands x Showtime (Sekai)",
        "modelPath": "v2/main/21_miku/v2_21miku_wonder",
        "modelFile": "21miku_wondershow2_t05.model3.json",
    },
]

# Motions oficiais da Miku no Project Sekai (com movimentação completa de braços, mãos, dedos e tronco)
SEKAI_MIKU_MOTIONS = {
    "Idle": [
        "w-cute01-pose",
        "w-cute01-tilthead",
        "w-cute02-pose",
    ],
    "Acenar": [
        "w-adult01-shakehand",
        "w-cool01-shakehand",
    ],
    "Feliz": [
        "w-cute01-glad03",
        "w-cute02-glad",
    ],
    "Rir": [
        "w-cute01-glad",
        "w-adult02-glad",
    ],
    "Pensar": [
        "w-adult01-think",
        "w-adult05-think",
    ],
    "Bravo": [
        "w-cool10-angry",
        "w-cute01-shakehead04",
    ],
    "Cantar": [
        "w-cute01-wink04",
        "w-cute02-guts",
        "w-cute01-nod04",
    ],
}


def _fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://sekai.best/",
            "Origin": "https://sekai.best",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def _fetch(url: str, dest: Path) -> bytes:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 100:
        return dest.read_bytes()
    data = _fetch_bytes(url)
    dest.write_bytes(data)
    return data


def _patch_motion_loop_fade(motion_path: Path) -> None:
    """Garante Fading suave em todas as curvas da motion Sekai."""
    try:
        data = json.loads(motion_path.read_text(encoding="utf-8"))
        meta = data.setdefault("Meta", {})
        meta["FadeInTime"] = 0.35
        meta["FadeOutTime"] = 0.35
        for curve in data.get("Curves", []):
            curve.setdefault("FadeInTime", 0.35)
            curve.setdefault("FadeOutTime", 0.35)
        motion_path.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass


def download_sekai_miku_models() -> None:
    motion_base_url = SEKAI_STORAGE + "live2d/motion/v2/main/21_miku/v2_21miku_motion_base/motion/"

    # Baixa as motions oficiais para um cache compartilhado primeiro e depois copia para cada traje da Miku
    shared_motions_dir = MODELS_DIR / "_sekai_miku_motions_cache"
    shared_motions_dir.mkdir(parents=True, exist_ok=True)

    print("1. Baixando motions oficiais de braços/corpo da Miku (Project Sekai)...")
    all_motion_names: set[str] = set()
    for mlist in SEKAI_MIKU_MOTIONS.values():
        all_motion_names.update(mlist)

    for mname in sorted(all_motion_names):
        dst = shared_motions_dir / f"{mname}.motion3.json"
        if not dst.is_file():
            try:
                _fetch(f"{motion_base_url}{mname}.motion3.json", dst)
                _patch_motion_loop_fade(dst)
                print(f"   -> Motion baixada: {mname}.motion3.json")
            except Exception as exc:
                print(f"   [Aviso] Falha ao baixar motion {mname}: {exc}")

    print("2. Baixando 4 Modelos Cubism 4 da Hatsune Miku (Project Sekai)...")
    for item in SEKAI_MIKU_MODELS:
        slug = item["slug"]
        model_dir = MODELS_DIR / slug
        model_dir.mkdir(parents=True, exist_ok=True)
        base_url = f"{SEKAI_STORAGE}live2d/model/{item['modelPath']}/"
        model_file = item["modelFile"]
        model_json_dst = model_dir / model_file

        print(f"   -> Baixando {item['title']} ({slug})...")
        raw = _fetch(base_url + model_file, model_json_dst)
        meta = json.loads(raw.decode("utf-8"))
        refs = meta.setdefault("FileReferences", {})

        # Baixa .moc3, .physics3.json e texturas
        for key in ("Moc", "Physics", "Pose"):
            rel = refs.get(key)
            if rel:
                _fetch(base_url + rel, model_dir / rel)
        for tex in refs.get("Textures", []):
            _fetch(base_url + tex, model_dir / tex)

        # Copia as motions oficiais do Project Sekai para a pasta motions/ do modelo
        local_motions_dir = model_dir / "motions"
        local_motions_dir.mkdir(parents=True, exist_ok=True)
        motions_dict: dict[str, list[dict[str, Any]]] = {}
        for group_name, mnames in SEKAI_MIKU_MOTIONS.items():
            group_list = []
            for mname in mnames:
                src_m = shared_motions_dir / f"{mname}.motion3.json"
                if src_m.is_file():
                    dst_m = local_motions_dir / f"{mname}.motion3.json"
                    if not dst_m.is_file():
                        dst_m.write_bytes(src_m.read_bytes())
                    group_list.append(
                        {
                            "Name": mname,
                            "File": f"motions/{mname}.motion3.json",
                            "FadeInTime": 0.35,
                            "FadeOutTime": 0.35,
                        }
                    )
            if group_list:
                motions_dict[group_name] = group_list

        refs["Motions"] = motions_dict
        model_json_dst.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"      [OK] Pronto: {model_json_dst.relative_to(PROJECT_ROOT)}")

    # Limpa o cache temporário de motions
    import shutil

    shutil.rmtree(shared_motions_dir, ignore_errors=True)


def fix_classic_miku_idle() -> None:
    """Remove os locks estáticos de PARAM_ARM_L/R e PARAM_HAIR_* do miku_idle_01.mtn."""
    idle_mtn = MODELS_DIR / "miku_sekai" / "mtn" / "miku_idle_01.mtn"
    if not idle_mtn.is_file():
        return
    lines = idle_mtn.read_text(encoding="utf-8").splitlines()
    filtered = [
        line
        for line in lines
        if not line.startswith("PARAM_ARM_") and not line.startswith("PARAM_HAIR_")
    ]
    idle_mtn.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    print("3. miku_idle_01.mtn ajustado para liberar braços e física de cabelo!")


if __name__ == "__main__":
    download_sekai_miku_models()
    fix_classic_miku_idle()
    print("Todos os modelos da Hatsune Miku (Project Sekai) estão prontos!")
