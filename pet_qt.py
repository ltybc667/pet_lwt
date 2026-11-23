import json
import os
import random
import re
import shutil
import sys
import winreg
import ctypes
import urllib.request
import webbrowser
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageSequence
from PySide6.QtCore import QAbstractNativeEventFilter, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSystemTrayIcon, QVBoxLayout, QWidget,
)

BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PETS = BASE / "pets"
CONFIG = Path(os.getenv("APPDATA", str(Path.home()))) / "DesktopPet" / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "pet_lwt"
SIZES = {"Маленький": 128, "Средний": 192, "Большой": 256, "Очень большой": 320}
SPEEDS = {"Медленно": 1.8, "Обычно": 1.0, "Быстро": 0.55}
BEHAVIORS = {"Спокойный": "calm", "Все движения по очереди": "sequential", "Случайный": "random"}
ICON = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else BASE) / "icon.ico"
MUTEX_NAME = "Local\\pet_lwt_SingleInstance_v1"
APP_VERSION = "0.4.0"
REPO_RELEASES_URL = "https://github.com/ltybc667/pet_lwt/releases"
REPO_API_URL = "https://api.github.com/repos/ltybc667/pet_lwt/releases/latest"


def acquire_single_instance():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Не удалось создать системный мьютекс")
    if ctypes.get_last_error() == 183:
        kernel32.CloseHandle(handle)
        return None
    return handle


def foreground_is_fullscreen(excluded_hwnds=()):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd or int(hwnd) in {int(item) for item in excluded_hwnds}:
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    window_rect = (rect.left, rect.top, rect.right, rect.bottom)
    for screen in QApplication.screens():
        geometry = screen.geometry()
        screen_rect = (geometry.left(), geometry.top(), geometry.right() + 1, geometry.bottom() + 1)
        if window_rect == screen_rect:
            return True
    return False


def load_settings():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def startup_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return f'"{pythonw if pythonw.exists() else sys.executable}" "{BASE / "pet_qt.py"}"'


def is_startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, RUN_NAME)[0] == startup_command()
    except OSError:
        return False


def set_startup(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def discover_pets():
    pets = {}
    if PETS.exists():
        for path in sorted(PETS.iterdir()):
            if path.is_dir() and (path / "spritesheet.png").is_file():
                pets[path.name] = ("sheet", path / "spritesheet.png")
            elif path.is_file() and path.suffix.lower() == ".gif":
                pets[path.stem] = ("gif", path)
    return pets


def load_frames(pet):
    kind, path = pet
    animations = {}
    with Image.open(path) as source:
        if kind == "sheet":
            for row, count in [(0, 6), (1, 8), (2, 8), (3, 4), (4, 5), (5, 8), (6, 6), (7, 6), (8, 6)]:
                images = []
                for col in range(count):
                    image = source.crop((col * 192, row * 208, (col + 1) * 192, (row + 1) * 208)).convert("RGBA")
                    images.append((image, 350 if row == 0 else 220))
                animations[row] = images
        else:
            images = []
            for frame in ImageSequence.Iterator(source):
                images.append((frame.convert("RGBA"), max(70, frame.info.get("duration", 120))))
            animations[0] = images
    result = {}
    for name, images in animations.items():
        frames = []
        for image, duration in images:
            image.thumbnail((320, 320), Image.Resampling.LANCZOS)
            raw = image.tobytes("raw", "RGBA")
            qimage = QImage(raw, image.width, image.height, image.width * 4, QImage.Format_RGBA8888).copy()
            frames.append((QPixmap.fromImage(qimage), duration))
        result[name] = frames
    return result


class _Point(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _Msg(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND), ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD), ("pt", _Point),
    ]


class GlobalHotkeys(QAbstractNativeEventFilter):
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    WM_HOTKEY = 0x0312

    def __init__(self, callbacks):
        super().__init__()
        self.callbacks = callbacks
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.registered = []
        for hotkey_id, (modifiers, key) in {
            1: (self.MOD_CONTROL | self.MOD_SHIFT, ord("P")),
            2: (self.MOD_CONTROL | self.MOD_SHIFT, ord("H")),
            3: (self.MOD_CONTROL | self.MOD_SHIFT, ord("Q")),
        }.items():
            if self.user32.RegisterHotKey(None, hotkey_id, modifiers, key):
                self.registered.append(hotkey_id)

    def nativeEventFilter(self, event_type, message):
        if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = ctypes.cast(int(message), ctypes.POINTER(_Msg)).contents
            if msg.message == self.WM_HOTKEY and msg.wParam in self.callbacks:
                self.callbacks[msg.wParam]()
                return True, 0
        return False, 0

    def unregister(self):
        for hotkey_id in self.registered:
            self.user32.UnregisterHotKey(None, hotkey_id)
        self.registered.clear()


def parse_version(value):
    numbers = re.findall(r"\d+", str(value))
    return tuple(int(number) for number in numbers[:3]) or (0,)


class UpdateChecker(QThread):
    result = Signal(object)

    def run(self):
        try:
            request = urllib.request.Request(
                REPO_API_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "pet_lwt"},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.result.emit({
                "ok": True,
                "tag": data.get("tag_name", ""),
                "url": data.get("html_url", REPO_RELEASES_URL),
            })
        except Exception as exc:
            self.result.emit({"ok": False, "error": str(exc)})


class PetEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактор питомца")
        self.setMinimumWidth(360)
        self.source_path = None
        self.preview = QLabel("GIF не выбран")
        self.preview.setAlignment(Qt.AlignCenter)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Имя питомца")
        choose = QPushButton("Выбрать GIF…")
        choose.clicked.connect(self.choose_gif)
        save = QPushButton("Сохранить питомца")
        save.clicked.connect(self.save_pet)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self.preview)
        layout.addWidget(QLabel("Имя:"))
        layout.addWidget(self.name_edit)
        layout.addWidget(choose)
        layout.addLayout(buttons)

    def choose_gif(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать GIF", str(Path.home()), "Анимация GIF (*.gif)")
        if not path:
            return
        self.source_path = Path(path)
        if not self.name_edit.text().strip():
            self.name_edit.setText(self.source_path.stem)
        try:
            with Image.open(self.source_path) as image:
                image.seek(0)
                image = image.convert("RGBA")
                image.thumbnail((180, 180), Image.Resampling.LANCZOS)
                raw = image.tobytes("raw", "RGBA")
                qimage = QImage(raw, image.width, image.height, image.width * 4, QImage.Format_RGBA8888).copy()
                self.preview.setPixmap(QPixmap.fromImage(qimage))
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Редактор питомца", f"Не удалось открыть GIF: {exc}")
            self.source_path = None

    def save_pet(self):
        if self.source_path is None:
            QMessageBox.warning(self, "Редактор питомца", "Сначала выберите GIF.")
            return
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Редактор питомца", "Введите имя питомца.")
            return
        self.accept()


class DesktopPet(QWidget):
    def __init__(self, selected_name=None, on_add_pet=None, on_remove_pet=None, persist_selection=True):
        super().__init__()
        self.setWindowTitle("pet_lwt")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.on_add_pet = on_add_pet
        self.on_remove_pet = on_remove_pet
        self.persist_selection = persist_selection
        self.settings = load_settings()
        self.paused = bool(self.settings.get("paused", False))
        self.auto_pause_enabled = bool(self.settings.get("auto_pause", True))
        self.auto_paused = False
        self.speed_factor = float(self.settings.get("speed_factor", 1.0))
        if self.speed_factor not in SPEEDS.values():
            self.speed_factor = 1.0
        self.behavior = self.settings.get("behavior", "random")
        if self.behavior not in BEHAVIORS.values():
            self.behavior = "random"
        self.size_px = self.settings.get("size", 192)
        if self.size_px not in SIZES.values():
            self.size_px = 192
        self.resize(self.size_px, self.size_px)
        self.pets = discover_pets()
        if not self.pets:
            QMessageBox.critical(None, "Питомец", "Добавьте GIF или папку со spritesheet.png в папку pets.")
            raise SystemExit(1)
        self.animations = {}
        self.scaled_animations = {}
        self.animation = 0
        self.index = 0
        self.current_pixmap = None
        self.idle_cycles = 0
        self.last_special = None
        self.special_cursor = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.load_timer = QTimer(self)
        self.load_timer.timeout.connect(self.check_fullscreen_app)
        self.load_timer.start(2000)
        selected = selected_name or self.settings.get("pet")
        self.select_pet(selected if selected in self.pets else next(iter(self.pets)))
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(self.settings.get("x", screen.right() - self.size_px - 40),
                  self.settings.get("y", screen.bottom() - self.size_px - 40))
        self.drag_offset = None

    def select_pet(self, name):
        try:
            self.animations = load_frames(self.pets[name])
            self.rebuild_scaled_frames()
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Питомец", f"Не удалось открыть {name}: {exc}")
            return
        self.index = 0
        self.animation = 0
        self.idle_cycles = 0
        self.last_special = None
        self.special_cursor = 0
        if self.persist_selection:
            self.settings["pet"] = name
            save_settings(self.settings)
        self.next_frame()

    def next_frame(self):
        frames = self.animations[self.animation]
        self.current_pixmap = self.scaled_animations[self.animation][self.index]
        duration = max(20, round(frames[self.index][1] * self.speed_factor))
        self.update()
        if not self.paused and not self.auto_paused:
            self.timer.start(duration)
        self.index += 1
        if self.index >= len(frames):
            self.index = 0
            specials = [key for key in self.animations if key != 0]
            if specials:
                if self.animation == 0:
                    self.idle_cycles += 1
                    if self.idle_cycles >= 2:
                        if self.behavior == "calm":
                            self.idle_cycles = 0
                            return
                        if self.behavior == "sequential":
                            self.animation = specials[self.special_cursor % len(specials)]
                            self.special_cursor += 1
                        else:
                            choices = [key for key in specials if key != self.last_special] or specials
                            self.animation = random.choice(choices)
                        self.last_special = self.animation
                        self.idle_cycles = 0
                else:
                    self.animation = 0

    def paintEvent(self, event):
        if self.current_pixmap:
            painter = QPainter(self)
            painter.drawPixmap((self.width() - self.current_pixmap.width()) // 2,
                               self.height() - self.current_pixmap.height(), self.current_pixmap)

    def rebuild_scaled_frames(self):
        self.scaled_animations = {
            name: [pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                   for pixmap, _ in frames]
            for name, frames in self.animations.items()
        }
        if self.current_pixmap is not None and self.animation in self.scaled_animations:
            self.current_pixmap = self.scaled_animations[self.animation][(self.index - 1) % len(self.scaled_animations[self.animation])]

    def hideEvent(self, event):
        self.timer.stop()
        self.load_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        self.load_timer.start(2000)
        self.check_fullscreen_app()
        self.restart_timer()
        super().showEvent(event)

    def restart_timer(self):
        if self.animations and not self.paused and not self.auto_paused:
            base_duration = self.animations[self.animation][(self.index - 1) % len(self.animations[self.animation])][1]
            self.timer.start(max(20, round(base_duration * self.speed_factor)))

    def check_fullscreen_app(self):
        if not self.auto_pause_enabled:
            return
        own_windows = [self.winId()]
        fullscreen = foreground_is_fullscreen(own_windows)
        if fullscreen and not self.auto_paused:
            self.auto_paused = True
            self.timer.stop()
        elif not fullscreen and self.auto_paused:
            self.auto_paused = False
            self.restart_timer()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_offset = None
            self.remember_position()

    def contextMenuEvent(self, event):
        self.pets = discover_pets()
        menu = QMenu(self)
        for name in self.pets:
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.settings.get("pet"))
            action.triggered.connect(lambda checked=False, n=name: self.select_pet(n))
        size_menu = menu.addMenu("Размер")
        for label, size in SIZES.items():
            action = size_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(size == self.size_px)
            action.triggered.connect(lambda checked=False, s=size: self.change_size(s))
        animation_menu = menu.addMenu("Анимация")
        pause = animation_menu.addAction("Пауза")
        pause.setCheckable(True)
        pause.setChecked(self.paused)
        pause.triggered.connect(self.toggle_pause)
        animation_menu.addSeparator()
        for label, factor in SPEEDS.items():
            action = animation_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(abs(factor - self.speed_factor) < 0.01)
            action.triggered.connect(lambda checked=False, f=factor: self.set_speed(f))
        auto_pause = animation_menu.addAction("Автопауза в полноэкранном режиме")
        auto_pause.setCheckable(True)
        auto_pause.setChecked(self.auto_pause_enabled)
        auto_pause.triggered.connect(self.set_auto_pause)
        behavior_menu = menu.addMenu("Поведение")
        for label, behavior in BEHAVIORS.items():
            action = behavior_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(behavior == self.behavior)
            action.triggered.connect(lambda checked=False, b=behavior: self.set_behavior(b))
        if self.on_add_pet:
            extra_menu = menu.addMenu("Добавить ещё питомца")
            for name in sorted(self.pets):
                extra_menu.addAction(name, lambda checked=False, n=name: self.on_add_pet(n))
        if self.on_remove_pet:
            menu.addAction("Убрать этого питомца", self.on_remove_pet_callback)
        menu.addSeparator()
        menu.addAction("Редактор питомца…", self.open_editor)
        menu.addAction("Добавить GIF…", self.import_gif)
        menu.addAction("Проверить обновления", self.check_updates)
        menu.addAction("Открыть папку питомцев", lambda: os.startfile(PETS))
        startup = menu.addAction("Запускать с Windows")
        startup.setCheckable(True)
        startup.setChecked(is_startup_enabled())
        startup.triggered.connect(self.toggle_startup)
        menu.addSeparator()
        menu.addAction("Выход", QApplication.instance().quit)
        menu.exec(event.globalPos())

    def on_remove_pet_callback(self):
        self.on_remove_pet(self)

    def check_updates(self):
        if getattr(self, "update_checker", None) is not None and self.update_checker.isRunning():
            return
        self.update_checker = UpdateChecker(self)
        self.update_checker.result.connect(self.show_update_result)
        self.update_checker.start()

    def show_update_result(self, result):
        self.update_checker = None
        if not result.get("ok"):
            QMessageBox.warning(self, "Обновления", f"Не удалось проверить обновления:\n{result.get('error', 'неизвестная ошибка')}")
            return
        latest = result.get("tag", "")
        url = result.get("url", REPO_RELEASES_URL)
        if parse_version(latest) > parse_version(APP_VERSION):
            answer = QMessageBox.question(
                self,
                "Доступно обновление",
                f"Доступна версия {latest} (сейчас {APP_VERSION}).\nОткрыть страницу скачивания?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if answer == QMessageBox.Yes:
                webbrowser.open(url)
        else:
            QMessageBox.information(self, "Обновления", f"Установлена последняя версия ({APP_VERSION}).")

    def open_editor(self):
        dialog = PetEditorDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        stem = re.sub(r"[<>:\"/\\|?*]", "_", dialog.name_edit.text()).strip(" .") or "pet"
        destination = PETS / f"{stem}.gif"
        suffix = 2
        while destination.exists():
            destination = PETS / f"{stem}_{suffix}.gif"
            suffix += 1
        try:
            PETS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dialog.source_path, destination)
            self.pets = discover_pets()
            self.select_pet(destination.stem)
        except OSError as exc:
            QMessageBox.critical(self, "Редактор питомца", f"Не удалось сохранить питомца: {exc}")

    def import_gif(self):
        source_name, _ = QFileDialog.getOpenFileName(
            self, "Добавить питомца", str(Path.home()), "Анимация GIF (*.gif)"
        )
        if not source_name:
            return
        try:
            source = Path(source_name)
            stem = re.sub(r"[<>:\"/\\|?*]", "_", source.stem).strip(" .") or "pet"
            destination = PETS / f"{stem}.gif"
            suffix = 2
            while destination.exists():
                destination = PETS / f"{stem}_{suffix}.gif"
                suffix += 1
            PETS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            self.pets = discover_pets()
            self.select_pet(destination.stem)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "Питомец", f"Не удалось добавить GIF: {exc}")

    def change_size(self, size):
        self.size_px = size
        self.resize(size, size)
        self.rebuild_scaled_frames()
        self.settings["size"] = size
        self.remember_position()
        self.update()

    def toggle_pause(self, paused):
        self.paused = paused
        self.settings["paused"] = paused
        if paused:
            self.timer.stop()
        else:
            self.restart_timer()
        save_settings(self.settings)

    def set_speed(self, factor):
        self.speed_factor = factor
        self.settings["speed_factor"] = factor
        save_settings(self.settings)
        if not self.paused:
            self.restart_timer()

    def set_auto_pause(self, enabled):
        self.auto_pause_enabled = enabled
        self.settings["auto_pause"] = enabled
        if not enabled:
            self.auto_paused = False
            self.restart_timer()
        else:
            self.check_fullscreen_app()
        save_settings(self.settings)

    def set_behavior(self, behavior):
        self.behavior = behavior
        self.settings["behavior"] = behavior
        self.idle_cycles = 0
        self.special_cursor = 0
        self.last_special = None
        save_settings(self.settings)

    def toggle_startup(self):
        try:
            set_startup(not is_startup_enabled())
        except OSError as exc:
            QMessageBox.critical(self, "Питомец", f"Не удалось изменить автозапуск: {exc}")

    def remember_position(self):
        self.settings.update(x=self.x(), y=self.y())
        save_settings(self.settings)

    def closeEvent(self, event):
        self.remember_position()
        super().closeEvent(event)


if __name__ == "__main__":
    mutex = acquire_single_instance()
    if mutex is None:
        raise SystemExit(0)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(ICON)))
    pet_windows = []

    def add_pet(name):
        window = DesktopPet(selected_name=name, on_add_pet=add_pet, on_remove_pet=remove_pet, persist_selection=False)
        offset = 32 * len(pet_windows)
        window.move(window.x() + offset, window.y() + offset)
        pet_windows.append(window)
        window.destroyed.connect(lambda: pet_windows.remove(window) if window in pet_windows else None)
        window.show()
        return window

    def remove_pet(window):
        if len(pet_windows) <= 1:
            QMessageBox.information(window, "Питомец", "Нельзя убрать последнего питомца.")
            return
        if window in pet_windows:
            pet_windows.remove(window)
        window.close()

    pet = DesktopPet(on_add_pet=add_pet, on_remove_pet=remove_pet)
    pet_windows.append(pet)
    pet.show()

    def show_all():
        for window in list(pet_windows):
            window.show()
            window.raise_()

    def hide_all():
        for window in list(pet_windows):
            window.hide()

    def remember_all():
        for window in list(pet_windows):
            window.remember_position()

    tray = QSystemTrayIcon(QIcon(str(ICON)), app)
    tray.setToolTip("pet_lwt")
    tray_menu = QMenu()
    tray_menu.addAction("Показать питомцев (Ctrl+Shift+H)", show_all)
    tray_menu.addAction("Скрыть питомцев", hide_all)
    tray_menu.addAction("Пауза (Ctrl+Shift+P)", lambda: [window.toggle_pause(not window.paused) for window in pet_windows])
    tray_menu.addAction("Проверить обновления", pet.check_updates)
    tray_menu.addSeparator()
    tray_menu.addAction("Выход", app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: show_all() if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()
    hotkeys = GlobalHotkeys({
        1: lambda: pet.toggle_pause(not pet.paused),
        2: lambda: (hide_all() if any(window.isVisible() for window in pet_windows) else show_all()),
        3: app.quit,
    })
    app.installNativeEventFilter(hotkeys)
    app.aboutToQuit.connect(remember_all)
    app.aboutToQuit.connect(tray.hide)
    app.aboutToQuit.connect(hotkeys.unregister)
    sys.exit(app.exec())

