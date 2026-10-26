"""Controlador de privacidade do microfone (Hard Mute) e seleção de dispositivo.

Este é o ÚNICO ponto de autorização de captura de áudio do projeto.
Regras de contrato:

1. Nenhum módulo pode abrir um stream de microfone sem antes chamar
   `require_capture_allowed()` (lança `MicMutedError` se mutado).
2. Todo módulo que abrir um dispositivo de áudio DEVE registrar um callback
   via `register_release_hook()` que FECHE o stream imediatamente. No Hard
   Mute, todos esses hooks são chamados -> o dispositivo é liberado de fato,
   não apenas "ignorado".
3. Por padrão a Rin inicia MUTADA (privacidade por padrão).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)

StateListener = Callable[[bool], None]  # recebe `muted`
DeviceListener = Callable[[int | None], None]  # recebe `device_index`
ReleaseHook = Callable[[], None]

_GENERIC_NAMES = (
    "mapeador de som",
    "sound mapper",
    "driver de captura",
    "primary sound capture",
)


@dataclass(frozen=True)
class AudioInputDevice:
    """Representa um dispositivo de entrada (microfone) disponível no sistema."""

    index: int | None  # None = Padrão do Sistema
    name: str
    samplerate: int = 16000
    channels: int = 1

    @property
    def label(self) -> str:
        return self.name


def list_input_devices() -> list[AudioInputDevice]:
    """Lista os microfones disponíveis no Windows, sem duplicatas por API."""
    default_entry = AudioInputDevice(index=None, name="Padrão do Windows")
    try:
        import sounddevice as sd

        apis = sd.query_hostapis()
        raw_devices = sd.query_devices()
    except Exception as exc:
        log.warning("Não foi possível listar dispositivos de áudio: %s", exc)
        return [default_entry]

    # Preferimos DirectSound (nomes completos no Windows e suporte a resampling automático)
    preferred_api_indices: list[int] = []
    for idx, api in enumerate(apis):
        api_name = str(api.get("name", "")).lower()
        if "directsound" in api_name:
            preferred_api_indices.insert(0, idx)
        elif "mme" in api_name or "wasapi" in api_name:
            preferred_api_indices.append(idx)

    seen_names: set[str] = set()
    devices: list[AudioInputDevice] = [default_entry]

    def _collect(api_filter: int | None) -> None:
        for idx, dev in enumerate(raw_devices):
            if int(dev.get("max_input_channels", 0)) <= 0:
                continue
            if api_filter is not None and dev.get("hostapi") != api_filter:
                continue
            name = str(dev.get("name", "")).strip()
            if not name:
                continue
            lower = name.lower()
            if any(g in lower for g in _GENERIC_NAMES):
                continue
            if lower in seen_names:
                continue
            seen_names.add(lower)
            devices.append(
                AudioInputDevice(
                    index=idx,
                    name=name,
                    samplerate=int(float(dev.get("default_samplerate", 16000)) or 16000),
                    channels=min(1, int(dev.get("max_input_channels", 1))),
                )
            )

    for api_idx in preferred_api_indices:
        _collect(api_idx)
    if len(devices) == 1:
        _collect(None)

    return devices


class MicMutedError(PermissionError):
    """Tentativa de capturar áudio com o microfone em Hard Mute."""


class MicController:
    def __init__(self, start_muted: bool = True, device_index: int | None = None) -> None:
        self._muted = start_muted
        self._device_index = device_index
        self._lock = threading.RLock()
        self._listeners: list[StateListener] = []
        self._device_listeners: list[DeviceListener] = []
        self._release_hooks: list[ReleaseHook] = []

    # ------------------------------------------------------------------ estado
    @property
    def is_muted(self) -> bool:
        with self._lock:
            return self._muted

    @property
    def device_index(self) -> int | None:
        with self._lock:
            return self._device_index

    def set_device(self, device_index: int | None) -> None:
        """Define o microfone ativo (None = Padrão do Windows) e notifica ouvintes."""
        with self._lock:
            if self._device_index == device_index:
                return
            self._device_index = device_index
            listeners = list(self._device_listeners)
        log.info("Microfone selecionado: device_index=%s", device_index)
        for listener in listeners:
            try:
                listener(device_index)
            except Exception:
                log.exception("Listener de troca de microfone falhou")

    def is_capture_allowed(self) -> bool:
        return not self.is_muted

    def require_capture_allowed(self) -> None:
        if self.is_muted:
            raise MicMutedError("Microfone em Hard Mute: captura de áudio bloqueada.")

    # ---------------------------------------------------------------- comandos
    def hard_mute(self) -> None:
        """Bloqueia captura e força a liberação de todos os dispositivos abertos."""
        with self._lock:
            already = self._muted
            self._muted = True
            hooks = list(self._release_hooks)
        for hook in hooks:
            try:
                hook()
            except Exception:  # um hook com erro não pode impedir o mute
                log.exception("Falha ao liberar dispositivo de áudio no Hard Mute")
        if not already:
            log.info("Microfone: HARD MUTE ativado")
            self._notify(True)

    def unmute(self) -> None:
        with self._lock:
            if not self._muted:
                return
            self._muted = False
        log.info("Microfone: liberado")
        self._notify(False)

    def toggle(self) -> bool:
        """Alterna o estado e devolve o novo valor de `is_muted`."""
        if self.is_muted:
            self.unmute()
        else:
            self.hard_mute()
        return self.is_muted

    # ------------------------------------------------------------- inscrições
    def add_listener(self, listener: StateListener) -> None:
        with self._lock:
            self._listeners.append(listener)

    def remove_listener(self, listener: StateListener) -> None:
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def add_device_listener(self, listener: DeviceListener) -> None:
        with self._lock:
            self._device_listeners.append(listener)

    def register_release_hook(self, hook: ReleaseHook) -> None:
        with self._lock:
            self._release_hooks.append(hook)

    def unregister_release_hook(self, hook: ReleaseHook) -> None:
        with self._lock:
            if hook in self._release_hooks:
                self._release_hooks.remove(hook)

    def _notify(self, muted: bool) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(muted)
            except Exception:
                log.exception("Listener do microfone falhou")
