"""Parser de emoções e ações (`[emocao]` + `[acao: ...]`).

Robustez esperada (o modelo nem sempre obedece perfeitamente):
- espaços/quebras de linha antes da tag;
- tag envolvida em markdown (`**[feliz]**`, `` `[feliz]` ``);
- maiúsculas e acentos (`[Pensativa]`, `[SURPRESA]`);
- sinônimos comuns (`[sarcástica]` -> `sarcasmo`, `[brava]` -> `irritada`);
- tags de ação (`[acao: acenar]`, `[acao: feliz]`, `[acao: rir]`, `[acao: pensar]`, `[acao: bravo]`, `[acao: cantar]`);
- tags de memória (`[MEMORIA: categoria | fato conciso | confirmado]`);
- detecção automática de cumprimentos do usuário ('oi', 'olá', 'e aí', 'bom dia', etc.) -> `acenar`;
- resposta sem tag ou com tag inválida -> emoção padrão (`neutra`).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

VALID_EMOTIONS: frozenset[str] = frozenset(
    {"neutra", "feliz", "irritada", "sarcasmo", "surpresa", "pensativa"}
)
DEFAULT_EMOTION = "neutra"

EMOTION_ALIASES: dict[str, str] = {
    "neutro": "neutra",
    "normal": "neutra",
    "calma": "neutra",
    "alegre": "feliz",
    "animada": "feliz",
    "contente": "feliz",
    "feliz": "feliz",
    "sorrindo": "feliz",
    "rindo": "feliz",
    "irritado": "irritada",
    "brava": "irritada",
    "bravo": "irritada",
    "raiva": "irritada",
    "zangada": "irritada",
    "sarcastica": "sarcasmo",
    "sarcastico": "sarcasmo",
    "ironia": "sarcasmo",
    "ironica": "sarcasmo",
    "surpresa": "surpresa",
    "surpreso": "surpresa",
    "surpresa!": "surpresa",
    "chocada": "surpresa",
    "pensativo": "pensativa",
    "reflexiva": "pensativa",
    "duvida": "pensativa",
    "pensar": "pensativa",
}

VALID_ACTIONS: frozenset[str] = frozenset(
    {
        "acenar",
        "feliz",
        "rir",
        "pensar",
        "bravo",
        "cantar",
        "dancar",
        "bater_palma",
        "pular",
        "concordar",
        "negar",
    }
)

ACTION_ALIASES: dict[str, str] = {
    "acena": "acenar",
    "acenando": "acenar",
    "wave": "acenar",
    "cumprimentar": "acenar",
    "tchau": "acenar",
    "oi": "acenar",
    "sorrir": "feliz",
    "sorriso": "feliz",
    "alegre": "feliz",
    "risada": "rir",
    "rindo": "rir",
    "gargalhar": "rir",
    "pensativa": "pensar",
    "pensando": "pensar",
    "refletir": "pensar",
    "irritada": "bravo",
    "irritado": "bravo",
    "brava": "bravo",
    "raiva": "bravo",
    "falar": "cantar",
    "cantando": "cantar",
    "musica": "cantar",
    "danca": "dancar",
    "dancando": "dancar",
    "mesmerizer": "dancar",
    "palmas": "bater_palma",
    "palma": "bater_palma",
    "aplaudir": "bater_palma",
    "pulo": "pular",
    "pulando": "pular",
    "sim": "concordar",
    "nao": "negar",
}

# Tag no início: opcionalmente envolvida por *, _ ou ` (markdown) e espaços.
_LEADING_TAG_RE = re.compile(r"^\s*[*_`]*\s*\[\s*([^\[\]\n]{1,35}?)\s*\]\s*[*_`]*[ \t]*[:\-–—]?\s*")
# Tag explícita de ação em qualquer posição: [acao: acenar], [ação: rir], [emote: cantar]
_ACTION_TAG_RE = re.compile(
    r"[*_`]*\[\s*(?:acao|ação|emote|action)\s*:\s*([^\[\]\n]{1,30}?)\s*\][*_`]*[ \t]*",
    re.IGNORECASE,
)
# Tag de memória persistente no final ou corpo: [MEMORIA: categoria | fato conciso | confirmado]
_MEMORY_TAG_RE = re.compile(
    r"[*_`]*\[\s*mem[oó]ria\s*:\s*([^\[\]\n]{1,500}?)\s*\][*_`]*[ \t]*",
    re.IGNORECASE,
)
# Qualquer tag de emoção válida "perdida" no meio do texto (removida do visível).
_ANY_TAG_RE = re.compile(r"\[\s*([A-Za-zÀ-ÿ!]{3,20})\s*\]\s?")

_GREETING_RE = re.compile(
    r"\b(?:oi+|ol[aá]+|opa+|e\s*a[ií]+|eae+|fala\s+rin|salve|hey+|hello+|hi+|bom\s+dia|boa\s+tarde|boa\s+noite|tchau|at[eé]\s+mais|acena\b|acenar\b)\b",
    re.IGNORECASE,
)
_LAUGH_RE = re.compile(r"\b(?:k{3,}|ha(?:ha)+|he(?:he)+|rs(?:rs)+|hihi+)\b", re.IGNORECASE)
_SING_RE = re.compile(r"\b(?:canta|cantar|m[uú]sica|vocaloid|dan[cç]a|dan[cç]ar)\b", re.IGNORECASE)


@dataclass(frozen=True)
class MemoryTag:
    category: str
    content: str
    confidence: str = "confirmado"


@dataclass(frozen=True)
class ParsedReply:
    emotion: str
    text: str
    raw: str
    had_valid_tag: bool
    action: str | None = None
    memories: tuple[MemoryTag, ...] = ()


def _strip_accents(value: str) -> str:
    nfkd = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_emotion(label: str | None) -> str | None:
    """Converte um rótulo bruto em uma emoção válida, ou `None` se desconhecido."""
    if not label:
        return None
    key = _strip_accents(label).strip().lower()
    if key in VALID_EMOTIONS:
        return key
    return EMOTION_ALIASES.get(key)


def normalize_action(label: str | None) -> str | None:
    """Converte um rótulo bruto de ação (`[acao: ...]`) em uma ação canônica."""
    if not label:
        return None
    key = _strip_accents(label).strip().lower().replace(" ", "_").replace("-", "_")
    if key in VALID_ACTIONS:
        return key
    return ACTION_ALIASES.get(key)


def infer_action_from_turn(
    user_text: str | None,
    reply_text: str | None,
    emotion: str,
    explicit_action: str | None = None,
) -> str | None:
    """Determina o gatilho de ação 2D ideal para o turno.

    Prioridade:
    1. Tag explícita `[acao: ...]` gerada pela IA.
    2. Cumprimento detectado na fala do usuário ('oi', 'olá', 'e aí', 'bom dia', etc.) -> `'acenar'`.
    3. Pedido de música/canto ou risada explícita -> `'cantar'` / `'rir'`.
    4. Mapeamento natural pela emoção (`feliz` -> `'feliz'`, `pensativa` -> `'pensar'`, `irritada` -> `'bravo'`).
    """
    if explicit_action:
        return explicit_action

    u_text = (user_text or "").strip()
    r_text = (reply_text or "").strip()

    if _GREETING_RE.search(u_text):
        return "acenar"
    if _SING_RE.search(u_text):
        return "cantar"
    if _LAUGH_RE.search(r_text):
        return "rir"

    if emotion == "feliz":
        return "feliz"
    if emotion == "pensativa":
        return "pensar"
    if emotion == "irritada":
        return "bravo"
    return None


def parse_reply(raw: str | None, default_emotion: str = DEFAULT_EMOTION) -> ParsedReply:
    """Extrai a emoção inicial, qualquer tag `[acao: ...]` e devolve o texto limpo."""
    raw = raw or ""
    emotion: str | None = None
    action: str | None = None
    text = raw

    # 0. Extrai tags [MEMORIA: categoria | fato | confirmado]
    memories_list: list[MemoryTag] = []
    for m in _MEMORY_TAG_RE.finditer(text):
        raw_val = m.group(1).strip()
        parts = [p.strip() for p in raw_val.split("|") if p.strip()]
        if len(parts) >= 2:
            cat = parts[0]
            cnt = parts[1]
            conf = parts[2] if len(parts) > 2 else "confirmado"
        elif len(parts) == 1:
            cat = "outros"
            cnt = parts[0]
            conf = "confirmado"
        else:
            continue
        memories_list.append(MemoryTag(category=cat, content=cnt, confidence=conf))
    text = _MEMORY_TAG_RE.sub("", text)

    # 1. Extrai todas as tags [acao: ...] presentes na resposta
    for m in _ACTION_TAG_RE.finditer(text):
        norm_act = normalize_action(m.group(1))
        if norm_act and action is None:
            action = norm_act
    text = _ACTION_TAG_RE.sub("", text)

    # 2. Extrai a tag inicial de emoção (ou caso a IA tenha colocado [acao:...] como tag simples)
    while True:
        match = _LEADING_TAG_RE.match(text)
        if not match:
            break
        raw_tag = match.group(1)
        if ":" in raw_tag:
            prefix, val = raw_tag.split(":", 1)
            if _strip_accents(prefix).strip().lower() in {"acao", "emote", "action"}:
                norm_act = normalize_action(val)
                if norm_act and action is None:
                    action = norm_act
                text = text[match.end():]
                continue
        maybe_emotion = normalize_emotion(raw_tag)
        if maybe_emotion is not None:
            if emotion is None:
                emotion = maybe_emotion
            text = text[match.end():]
            continue
        maybe_act = normalize_action(raw_tag)
        if maybe_act is not None and emotion is not None:
            if action is None:
                action = maybe_act
            text = text[match.end():]
            continue
        break

    # Remove tags de emoção válidas que tenham escapado para o meio do texto,
    # sem tocar em colchetes legítimos (ex.: listas Python `[1, 2]`).
    def _drop_known(m: re.Match[str]) -> str:
        return "" if _strip_accents(m.group(1)).lower() in VALID_EMOTIONS else m.group(0)

    text = _ANY_TAG_RE.sub(_drop_known, text).strip()

    if emotion is None and action is not None:
        # Se a IA enviou apenas [acao: ...], infere a emoção correspondente
        action_to_emotion = {
            "acenar": "feliz",
            "feliz": "feliz",
            "rir": "feliz",
            "cantar": "feliz",
            "dancar": "feliz",
            "pensar": "pensativa",
            "bravo": "irritada",
        }
        emotion = action_to_emotion.get(action, default_emotion)

    return ParsedReply(
        emotion=emotion or default_emotion,
        text=text,
        raw=raw,
        had_valid_tag=emotion is not None,
        action=action,
        memories=tuple(memories_list),
    )
