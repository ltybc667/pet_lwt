import json
import os
import random
import sys
import winreg
import ctypes
from pathlib import Path

from PIL import Image, ImageSequence
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget

BASE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
PETS = BASE / "pets"
CONFIG = Path(os.getenv("APPDATA", str(Path.home()))) / "DesktopPet" / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "pet_lwt"
SIZES = {"Маленький": 128, "Средний": 192, "Большой": 256, "Очень большой": 320}
ICON = (Path(sys._MEIPASS) if getattr(sys, "frozen", False) else BASE) / "icon.ico"
MUTEX_NAME = "Local\\pet_lwt_SingleInstance_v1"


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


class DesktopPet(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("pet_lwt")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.settings = load_settings()
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
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        selected = self.settings.get("pet")
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
        self.settings["pet"] = name
        save_settings(self.settings)
        self.next_frame()

    def next_frame(self):
        frames = self.animations[self.animation]
        self.current_pixmap = self.scaled_animations[self.animation][self.index]
        duration = frames[self.index][1]
        self.update()
        self.timer.start(duration)
        self.index += 1
        if self.index >= len(frames):
            self.index = 0
            specials = [key for key in self.animations if key != 0]
            if specials:
                if self.animation == 0:
                    self.idle_cycles += 1
                    if self.idle_cycles >= 2:
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
        super().hideEvent(event)

    def showEvent(self, event):
        if self.animations:
            self.timer.start(self.animations[self.animation][(self.index - 1) % len(self.animations[self.animation])][1])
        super().showEvent(event)

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
        menu.addSeparator()
        menu.addAction("Открыть папку питомцев", lambda: os.startfile(PETS))
        startup = menu.addAction("Запускать с Windows")
        startup.setCheckable(True)
        startup.setChecked(is_startup_enabled())
        startup.triggered.connect(self.toggle_startup)
        menu.addSeparator()
        menu.addAction("Выход", QApplication.instance().quit)
        menu.exec(event.globalPos())

    def change_size(self, size):
        self.size_px = size
        self.resize(size, size)
        self.rebuild_scaled_frames()
        self.settings["size"] = size
        self.remember_position()
        self.update()

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
    pet = DesktopPet()
    pet.show()
    tray = QSystemTrayIcon(QIcon(str(ICON)), app)
    tray.setToolTip("pet_lwt")
    tray_menu = QMenu()
    tray_menu.addAction("Показать питомца", lambda: (pet.show(), pet.raise_()))
    tray_menu.addAction("Скрыть питомца", pet.hide)
    tray_menu.addSeparator()
    tray_menu.addAction("Выход", app.quit)
    tray.setContextMenu(tray_menu)
    tray.activated.connect(lambda reason: pet.show() if reason == QSystemTrayIcon.DoubleClick else None)
    tray.show()
    app.aboutToQuit.connect(pet.remember_position)
    app.aboutToQuit.connect(tray.hide)
    sys.exit(app.exec())
