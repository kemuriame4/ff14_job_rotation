from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt

_SHIFTED_CHARS = {
    "!": "1",
    "@": "2",
    "#": "3",
    "$": "4",
    "%": "5",
    "^": "6",
    "&": "7",
    "*": "8",
    "(": "9",
    ")": "0",
    "_": "-",
    "+": "=",
    "{": "[",
    "}": "]",
    "|": "\\",
    ":": ";",
    '"': "'",
    "<": ",",
    ">": ".",
    "?": "/",
}

_QT_SPECIAL = {
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Insert: "insert",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Comma: ",",
    Qt.Key.Key_Period: ".",
    Qt.Key.Key_Slash: "/",
    Qt.Key.Key_Semicolon: ";",
    Qt.Key.Key_Apostrophe: "'",
    Qt.Key.Key_Minus: "-",
    Qt.Key.Key_Equal: "=",
    Qt.Key.Key_BracketLeft: "[",
    Qt.Key.Key_BracketRight: "]",
    Qt.Key.Key_Backslash: "\\",
    Qt.Key.Key_QuoteLeft: "`",
    Qt.Key.Key_Underscore: "_",
    Qt.Key.Key_Plus: "+",
}

_MOD_ORDER = ("ctrl", "alt", "shift")
_MOD_LABELS = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}


def canonical_from_qt(event: Any) -> str | None:
    key = event.key()
    base: str | None = None
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        base = chr(key).lower()
    elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        base = chr(key)
    elif Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
        base = f"f{key - Qt.Key.Key_F1 + 1}"
    elif key in _QT_SPECIAL:
        base = _QT_SPECIAL[key]
    else:
        text = event.text()
        if text and len(text) == 1 and text.isprintable():
            char = text.lower()
            base = _SHIFTED_CHARS.get(char, char)
    if not base or base in ("ctrl", "alt", "shift"):
        return None

    mods = []
    if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
        mods.append("ctrl")
    if event.modifiers() & Qt.KeyboardModifier.AltModifier:
        mods.append("alt")
    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
        mods.append("shift")
    parts = [m for m in _MOD_ORDER if m in mods] + [base]
    return "+".join(parts)


def pynput_key_info(key: Any) -> tuple[str | None, str | None]:
    """Return (base_key, modifier). modifier is set for pure modifier keys."""
    try:
        from pynput.keyboard import Key, KeyCode
    except ImportError:
        return None, None

    if isinstance(key, Key):
        name = key.name
        modifier = {
            "ctrl_l": "ctrl",
            "ctrl_r": "ctrl",
            "alt_l": "alt",
            "alt_r": "alt",
            "alt_gr": "alt",
            "shift_l": "shift",
            "shift_r": "shift",
        }.get(name)
        if modifier:
            return None, modifier
        special = {
            "space": "space",
            "enter": "enter",
            "esc": "esc",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "insert": "insert",
            "home": "home",
            "end": "end",
            "page_up": "pageup",
            "page_down": "pagedown",
            "left": "left",
            "right": "right",
            "up": "up",
            "down": "down",
            "caps_lock": "caps_lock",
            "num_lock": "num_lock",
        }.get(name, name)
        return special.lower(), None

    if isinstance(key, KeyCode):
        vk = key.vk
        if vk is not None:
            if 0x30 <= vk <= 0x39:
                return chr(vk), None
            if 0x41 <= vk <= 0x5A:
                return chr(vk).lower(), None
            if 0x60 <= vk <= 0x69:
                return str(vk - 0x60), None
        char = key.char
        if char:
            low = char.lower()
            return _SHIFTED_CHARS.get(low, low), None
    return None, None


def combine_key(base: str, mods: set[str]) -> str:
    parts = [m for m in _MOD_ORDER if m in mods] + [base]
    return "+".join(parts)


def pretty_key(key: str) -> str:
    key = key.strip()
    if not key:
        return "未绑定"
    parts = [p for p in key.split("+") if p]
    if not parts:
        return "未绑定"
    head = [
        _MOD_LABELS.get(p, p.upper() if len(p) == 1 and p.isalpha() else p)
        for p in parts[:-1]
    ]
    tail = parts[-1]
    tail_label = tail.upper() if len(tail) == 1 and tail.isalpha() else tail
    return " + ".join(head + [tail_label])
