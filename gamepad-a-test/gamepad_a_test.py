"""One-shot Windows XInput A diagnostic. No game memory or mouse injection."""
from __future__ import annotations

import ctypes
import logging
import math
import os
from pathlib import Path
import re
import time


class TapSession:
    """Bounded A pulse; UI calls tick on its event loop, with no queued repeats."""

    def __init__(self, pad, button, emit, hold_seconds=0.18):
        self.pad, self.button, self.emit = pad, button, emit
        self.hold_seconds = hold_seconds
        self.phase = "idle"
        self.deadline = 0.0
        self.require_game = True

    @property
    def active(self):
        return self.phase in ("waiting", "down")

    def neutral(self):
        self.pad.reset()
        self.pad.update()

    def begin(self, now, delay, require_game=True):
        if self.active:
            raise RuntimeError("Тест уже запущен")
        if not 3 <= delay <= 60:
            raise ValueError("Задержка должна быть от 3 до 60 секунд")
        self.neutral()
        self.require_game = require_game
        self.deadline = now + delay
        self.phase = "waiting"
        self.emit(f"Ожидание {delay:g} с. Будет отправлено только ОДНО нажатие A.")

    def cancel(self, reason="Отменено"):
        # Invalidate pending work before attempting a driver operation.
        self.phase = "idle"
        self.neutral()
        self.emit(reason + "; отправлено нейтральное состояние геймпада.")

    def tick(self, now, game_focused):
        if not self.active:
            return
        if self.phase == "down" and self.require_game and not game_focused:
            self.cancel("Окно игры потеряло фокус")
            return
        if now < self.deadline:
            return
        if self.phase == "waiting":
            if self.require_game and not game_focused:
                self.cancel("A не отправлена: активное окно не похоже на AION2")
                return
            self.phase = "down"
            self.deadline = now + self.hold_seconds
            try:
                self.pad.press_button(button=self.button)
                self.pad.update()
            except BaseException:
                self.phase = "idle"
                try:
                    self.neutral()
                except Exception:
                    pass
                raise
            self.emit("TX: A нажата на виртуальном геймпаде (не подтверждение игры).")
        else:
            # No repeat is scheduled, including when reset/update fails.
            self.phase = "idle"
            self.neutral()
            self.emit("TX: A отпущена. Тест завершён; результат в игре проверьте визуально.")


class WindowsProbe:
    def __init__(self):
        from ctypes import wintypes

        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetForegroundWindow.argtypes = []
        self.user32.GetForegroundWindow.restype = wintypes.HWND
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowTextW.restype = ctypes.c_int
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short

        class Gamepad(ctypes.Structure):
            _fields_ = [("buttons", ctypes.c_uint16), ("lt", ctypes.c_uint8),
                        ("rt", ctypes.c_uint8), ("lx", ctypes.c_int16),
                        ("ly", ctypes.c_int16), ("rx", ctypes.c_int16),
                        ("ry", ctypes.c_int16)]

        class State(ctypes.Structure):
            _fields_ = [("packet", ctypes.c_uint32), ("gamepad", Gamepad)]

        self.State = State
        self.xinput = None
        for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
            try:
                library = ctypes.WinDLL(name)
                library.XInputGetState.argtypes = [ctypes.c_uint32, ctypes.POINTER(State)]
                library.XInputGetState.restype = ctypes.c_uint32
                self.xinput = library
                break
            except OSError:
                pass

    def title(self):
        title = ctypes.create_unicode_buffer(1024)
        self.user32.GetWindowTextW(self.user32.GetForegroundWindow(), title, len(title))
        return title.value

    @staticmethod
    def is_game(title):
        return re.search(r"aion[\s_-]*2", title, re.IGNORECASE) is not None

    def escape_down(self):
        return bool(self.user32.GetAsyncKeyState(0x1B) & 0x8000)

    def states(self):
        result = {}
        if self.xinput:
            for slot in range(4):
                state = self.State()
                if self.xinput.XInputGetState(slot, ctypes.byref(state)) == 0:
                    result[slot] = state.gamepad.buttons
        return result


class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        from tkinter.scrolledtext import ScrolledText

        self.root = root
        self.probe = WindowsProbe()
        self.pad = self.session = None
        self.seen_a = set()
        self.before_a = set()
        self.readback_pending = False
        self.last_second = None
        self.closed = False
        # The title must not match the game foreground check.
        root.title("Проверка кнопки A — виртуальный Xbox 360")
        root.geometry("860x620")
        root.minsize(720, 560)
        root.protocol("WM_DELETE_WINDOW", self.close)
        panel = ttk.Frame(root, padding=14)
        panel.pack(fill="both", expand=True)
        ttk.Label(panel, text="Одно нажатие A через виртуальный Xbox 360",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(panel, wraplength=790, text=(
            "Сначала отключите приёмник F710 и другие геймпады. Подключите виртуальный "
            "геймпад кнопкой ниже. Для теста откройте курсор в игре физическим Alt, "
            "наведите его мышью на ресурс и дождитесь нажатия A."
        )).pack(anchor="w", pady=(8, 12))
        self.connect_button = ttk.Button(panel, text="1. Подключить виртуальный геймпад",
                                         command=self.connect)
        self.connect_button.pack(anchor="w")
        settings = ttk.Frame(panel)
        settings.pack(fill="x", pady=12)
        ttk.Label(settings, text="Задержка, секунд:").pack(side="left")
        self.delay = tk.StringVar(value="8")
        ttk.Spinbox(settings, from_=3, to=60, width=5, textvariable=self.delay).pack(side="left", padx=8)
        self.require_game = tk.BooleanVar(value=True)
        ttk.Checkbutton(panel, text="Отправлять A только при активном окне AION2",
                        variable=self.require_game).pack(anchor="w")
        ttk.Label(panel, wraplength=790, text=(
            "Для проверки в joy.cpl снимите эту галочку. Во время теста не нажимайте A "
            "на физическом геймпаде. Esc отменяет ожидающее нажатие и отпускает A."
        )).pack(anchor="w", pady=(4, 10))
        actions = ttk.Frame(panel)
        actions.pack(fill="x")
        self.test_button = ttk.Button(actions, text="2. Одно A после задержки",
                                       command=self.start, state="disabled")
        self.test_button.pack(side="left")
        ttk.Button(actions, text="СТОП / отпустить A", command=self.stop).pack(side="left", padx=10)
        self.status = tk.StringVar(value="Геймпад ещё не подключён")
        ttk.Label(panel, textvariable=self.status, wraplength=790).pack(anchor="w", pady=12)
        self.log_widget = ScrolledText(panel, height=15, wrap="word", state="disabled")
        self.log_widget.pack(fill="both", expand=True)
        self.logger = logging.getLogger("gamepad_a_test")
        self.logger.setLevel(logging.INFO)
        try:
            handler = logging.FileHandler(Path(__file__).with_name("gamepad_test.log"), encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        except OSError:
            pass
        self.log("Тест ничего не устанавливает. Нужны vgamepad и установленный ViGEmBus; см. README_RU.txt.")
        self.log("A на Xbox-геймпаде — не клавиша A клавиатуры и не ЛКМ.")
        root.after(20, self.tick)

    def log(self, message):
        self.logger.info(message)
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", time.strftime("%H:%M:%S ") + message + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def connect(self):
        if self.pad is not None:
            return
        self.connect_button.configure(state="disabled")
        try:
            existing = set(self.probe.states())
            import vgamepad as vg
            self.pad = vg.VX360Gamepad()
            self.session = TapSession(self.pad, vg.XUSB_BUTTON.XUSB_GAMEPAD_A, self.log)
            self.session.neutral()
            self.status.set("Виртуальный геймпад подключён. Можно запускать игру и тест.")
            self.log("Создан виртуальный Xbox 360. Автоматических нажатий при подключении нет.")
            self.test_button.configure(state="normal")
            self.root.after(1500, lambda: self.report_slots(existing))
        except Exception as exc:
            self.log(f"Ошибка подключения: {type(exc).__name__}: {exc}")
            self.log("Проверьте установку vgamepad/ViGEmBus, затем перезапустите тест. Подробности в README_RU.txt.")
            self.status.set("Подключение не удалось; см. журнал.")
            self.connect_button.configure(state="normal")
            if self.session is not None:
                self.safe_neutral()
            self.session = self.pad = None

    def report_slots(self, existing):
        if self.closed:
            return
        states = self.probe.states()
        self.log(f"XInput: подключённые слоты (0–3): {sorted(states)}; новые: {sorted(set(states) - existing)}.")
        if existing:
            self.log("Ещё до подключения были другие XInput-устройства. Для чистого теста отключите их и перезапустите программу.")
        if not states:
            self.log("Windows пока не видит XInput-устройство. Проверьте драйвер и joy.cpl.")

    def start(self):
        if self.session is None or self.session.active:
            return
        try:
            delay = float(self.delay.get().replace(",", "."))
            self.seen_a.clear()
            self.before_a.clear()
            self.readback_pending = True
            self.last_second = None
            self.session.begin(time.monotonic(), delay, self.require_game.get())
            self.test_button.configure(state="disabled")
        except Exception as exc:
            self.readback_pending = False
            self.log(f"Не удалось начать: {type(exc).__name__}: {exc}")

    def safe_neutral(self):
        if self.session:
            self.session.phase = "idle"
            try:
                self.session.neutral()
            except Exception as exc:
                self.log(f"Драйвер не подтвердил сброс: {type(exc).__name__}: {exc}. Закройте тест, чтобы отключить виртуальное устройство.")

    def stop(self):
        self.safe_neutral()
        self.readback_pending = False
        self.status.set("Остановлено. Новых нажатий не запланировано.")
        self.log("СТОП: запрошено нейтральное состояние, ожидающее нажатие отменено.")
        if self.pad:
            self.test_button.configure(state="normal")

    def tick(self):
        if self.closed:
            return
        try:
            if self.session and self.session.active:
                if self.probe.escape_down():
                    self.stop()
                else:
                    was = self.session.phase
                    title = self.probe.title()
                    now = time.monotonic()
                    if was == "waiting":
                        self.before_a = {s for s, b in self.probe.states().items() if b & 0x1000}
                        second = max(0, math.ceil(self.session.deadline - now))
                        self.status.set(f"До одного нажатия A: {second} с. Переключитесь в игру и наведите курсор.")
                        if second != self.last_second:
                            self.last_second = second
                            self.log(f"Отсчёт: {second} с")
                        if now >= self.session.deadline:
                            self.log("Активное окно перед тестом: " + repr(title))
                    # Sample the held state before the release deadline as well.
                    if was == "down":
                        self.seen_a.update(s for s, b in self.probe.states().items() if b & 0x1000)
                    self.session.tick(now, self.probe.is_game(title))
                    if self.session.phase == "down":
                        self.seen_a.update(s for s, b in self.probe.states().items() if b & 0x1000)
                        self.status.set("Отправлено A; ожидается отпускание.")
                    if not self.session.active:
                        self.finish_readback()
                        self.test_button.configure(state="normal")
        except Exception as exc:
            self.log(f"Ошибка теста: {type(exc).__name__}: {exc}")
            self.stop()
        self.root.after(20, self.tick)

    def finish_readback(self):
        if not self.readback_pending:
            return
        self.readback_pending = False
        observed = self.seen_a - self.before_a
        if observed:
            self.log(f"Windows XInput: A прочитана в слотах {sorted(observed)}. Это подтверждение Windows, не игры.")
            states = self.probe.states()
            released = [s for s in observed if s in states and not states[s] & 0x1000]
            self.log(f"Windows XInput: A уже отпущена в слотах {released}.")
        else:
            self.log("Windows XInput не подтвердил переход A в нажатое состояние. Не считать это доказательством блокировки игрой.")
        self.status.set("Тест закончен. Проверьте таргет в игре и записи Windows XInput в журнале.")

    def close(self):
        self.closed = True
        self.safe_neutral()
        self.session = self.pad = None
        self.root.destroy()


def main():
    if os.name != "nt":
        print("This diagnostic is for Windows only; no input was generated.")
        return 2
    import tkinter as tk
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
