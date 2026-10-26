"""Clientes de IA (o "cérebro" da Rin).

- `GeminiBrain`: usa o SDK oficial `google-genai`.
- `OfflineBrain`: respostas simuladas quando não há API key (testar UI sem custo).

Todos implementam o protocolo `Brain`, então o roteador não depende do provedor.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Protocol, Sequence

from src.memory.session import Turn

log = logging.getLogger(__name__)


class BrainError(RuntimeError):
    """Falha ao gerar resposta (rede, cota, chave inválida...)."""


class Brain(Protocol):
    name: str

    def generate(self, system_instruction: str, history: Sequence[Turn]) -> str:
        """Recebe o prompt de sistema + histórico (terminando no usuário) e
        devolve a resposta BRUTA do modelo (com a tag de emoção)."""
        ...


DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.5-flash",
    "gemini-3.8-flash",
    "gemini-flash-latest",
)


class GeminiBrain:
    """Cérebro rápido via `google-genai` (Gemini Developer API)."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        temperature: float = 0.9,
        max_output_tokens: int = 600,
        thinking_budget: int | None = 0,
        fallback_models: Sequence[str] = DEFAULT_FALLBACK_MODELS,
        timeout_ms: int = 15000,
    ) -> None:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - depende do ambiente
            raise BrainError(
                "Pacote 'google-genai' não instalado. Rode: pip install -r requirements.txt"
            ) from exc

        self._types = types
        # Desativa os 5 retries longos do SDK (que travavam por >60s em erros 503/504)
        # e usa timeout curto (mínimo permitido pela API do Google é 10s).
        http_options = types.HttpOptions(
            timeout=max(10000, timeout_ms),
            retry_options=types.HttpRetryOptions(attempts=1),
        )
        self._client = genai.Client(api_key=api_key, http_options=http_options)
        self.model = model
        self.name = f"Gemini ({model})"
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.thinking_budget = thinking_budget
        self.fallback_models = tuple(dict.fromkeys([model, *fallback_models]))

    def _build_config(self, system_instruction: str, model_name: str):
        types = self._types
        kwargs = dict(
            system_instruction=system_instruction,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )
        # Nem todos os modelos (ex: flash-lite) aceitam thinking_config
        if (
            self.thinking_budget is not None
            and "lite" not in model_name
            and model_name.startswith(("gemini-2.5", "gemini-3.5", "gemini-3.6", "gemini-3.8"))
        ):
            try:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)
            except Exception:
                pass
        return types.GenerateContentConfig(**kwargs)

    def _to_contents(self, history: Sequence[Turn]):
        types = self._types
        contents = []
        for turn in history:
            # Para o modelo, reenviamos a resposta bruta (com tag) para reforçar o formato.
            text = turn.raw if (turn.role == "model" and turn.raw) else turn.text
            contents.append(types.Content(role=turn.role, parts=[types.Part(text=text)]))
        return contents

    def generate(self, system_instruction: str, history: Sequence[Turn]) -> str:
        contents = self._to_contents(history)
        last_exc: Exception | None = None

        for candidate in self.fallback_models:
            # Para o modelo principal ou de alta demanda transitória, tenta retry breve
            max_attempts = 2 if candidate == self.fallback_models[0] else 1
            for attempt in range(max_attempts):
                try:
                    response = self._client.models.generate_content(
                        model=candidate,
                        contents=contents,
                        config=self._build_config(system_instruction, candidate),
                    )
                    text = (getattr(response, "text", None) or "").strip()
                    if not text:
                        raise BrainError("O modelo retornou uma resposta vazia (possível bloqueio de segurança).")
                    if candidate != self.model:
                        log.info("Fallback automático acionado: %s -> %s", self.model, candidate)
                        self.model = candidate
                        self.name = f"Gemini ({candidate})"
                    return text
                except Exception as exc:
                    last_exc = exc
                    err_str = str(exc)
                    is_transient = (
                        "503" in err_str
                        or "504" in err_str
                        or "429" in err_str
                        or "high demand" in err_str.lower()
                        or "deadline" in err_str.lower()
                    )
                    if is_transient and attempt < max_attempts - 1:
                        log.warning(
                            "Modelo '%s' com alta demanda transitória (%s). Retentando em 1s...",
                            candidate,
                            exc,
                        )
                        time.sleep(1.0)
                        continue
                    log.warning("Modelo '%s' indisponível/lento (%s). Tentando próximo modelo...", candidate, exc)
                    break

        log.error("Todos os modelos falharam. Último erro: %s", last_exc)
        err_msg = str(last_exc)
        if "503" in err_msg or "high demand" in err_msg.lower():
            raise BrainError(
                "Os servidores do Google estão enfrentando alta demanda temporária no momento (Erro 503). "
                "Por favor, tente novamente em alguns instantes."
            ) from last_exc
        raise BrainError(err_msg) from last_exc


class OfflineBrain:
    """Cérebro simulado: permite abrir e testar a interface sem API key."""

    name = "Offline (simulado)"

    _REPLIES = (
        "[sarcasmo] Conversando comigo sem API key? Ousado. Coloca a GEMINI_API_KEY no .env que eu ganho cérebro de verdade.",
        "[pensativa] Hmm... eu até responderia algo inteligente, mas estou em modo offline. Configura o .env pra mim?",
        "[feliz] Oi! A interface tá funcionando direitinho. Só falta a chave do Gemini pra eu pensar de verdade.",
        "[neutra] Modo offline ativo. Recebi sua mensagem: \"{msg}\".",
        "[surpresa] Ué, você já está testando? Nem me deu um cérebro ainda!",
    )

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def generate(self, system_instruction: str, history: Sequence[Turn]) -> str:
        last = history[-1].text if history else ""
        return self._rng.choice(self._REPLIES).format(msg=last[:80])
