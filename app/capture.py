from __future__ import annotations

import time

from PySide6.QtCore import QObject, Signal


class GlobalKeyListener(QObject):
    """Captures physical key presses globally through pynput."""

    key_pressed = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._listener = None
        self._mods: set[str] = set()
        # 物理基础键 -> 按下时发出的组合键；记录按下 / 释放状态，按住期间不再重复上报。
        self._held: dict[str, str] = {}
        self._running = False

    @staticmethod
    def available() -> bool:
        try:
            import pynput.keyboard  # noqa: F401

            return True
        except ImportError:
            return False

    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        if self._running:
            return True
        try:
            from pynput import keyboard

            from .keys import combine_key, pynput_key_info

            self._keyboard = keyboard
            self._combine = combine_key
            self._key_info = pynput_key_info
            self._mods.clear()
            self._held.clear()
            self._listener = keyboard.Listener(
                on_press=self._on_press, on_release=self._on_release
            )
            self._listener.daemon = True
            self._listener.start()
            self._running = True
            return True
        except Exception as exc:  # pragma: no cover - platform dependent
            self._running = False
            self._listener = None
            self.error.emit(str(exc))
            return False

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        self._running = False
        self._mods.clear()
        self._held.clear()
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                pass

    def _on_press(self, key) -> None:
        try:
            base, modifier = self._key_info(key)
            if modifier:
                self._mods.add(modifier)
                return
            if not base:
                return
            # 该物理键仍处于按下状态：自动重复，或修饰键先释放后系统继续上报基础键
            # （如 Ctrl+1 变成 1）。此时保持静默，单键热键不会被触发。
            if base in self._held:
                return
            canonical = self._combine(base, self._mods)
            self._held[base] = canonical
            self.key_pressed.emit(canonical)
        except Exception as exc:  # pragma: no cover
            self.error.emit(str(exc))

    def _on_release(self, key) -> None:
        try:
            base, modifier = self._key_info(key)
            if modifier:
                self._mods.discard(modifier)
                return
            if base:
                self._held.pop(base, None)
        except Exception:
            pass


def timestamp() -> float:
    return time.perf_counter()
