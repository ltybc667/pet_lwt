# pet_lwt

Небольшой анимированный питомец для рабочего стола Windows. Работает самостоятельно, без ChatGPT и подключения к интернету.

## Установка

1. Скачайте архив `pet_lwt-windows.zip` из Releases и распакуйте его.
2. Оставьте папку `pets` рядом с `pet_lwt.exe`.
3. Запустите `pet_lwt.exe`. Установка Python не требуется.

Для удаления закройте питомца через меню и удалите распакованную папку. Настройки хранятся в `%APPDATA%\DesktopPet\settings.json`.

## Управление

- Перетаскивание левой кнопкой мыши перемещает питомца.
- Правый клик открывает выбор питомца, размер, автозапуск и выход.
- Значок в области уведомлений Windows позволяет показать, скрыть или закрыть приложение.
- Повторный запуск не создаёт вторую копию.
- Для добавления питомца положите анимированный GIF в папку `pets`. Он появится в меню при следующем правом клике.

Приложение также поддерживает папку с `spritesheet.png` размером 1536 × 2288 пикселей: сетка 8 × 11, ячейка 192 × 208. Для анимаций используются строки 0–8.

## Запуск из исходников

Требуется Python 3.10 или новее на Windows:

```powershell
python -m pip install -r requirements.txt
python pet_qt.py
```

Для сборки `.exe` установите PyInstaller (`python -m pip install pyinstaller`) и выполните `powershell -ExecutionPolicy Bypass -File .\build.ps1`. Готовый файл появится в `dist`. Для воспроизводимой сборки используйте зависимости из `requirements.txt`; скрипт исключает из PATH установленный отдельно Poppler, чья DLL может конфликтовать с Qt.

## Публикация

Репозиторий содержит только исходный код, иконку и нейтрального примерного питомца. Свои изображения добавляйте локально; папка `pets` настроена так, что Git учитывает только `ExampleCat.gif`.

Лицензия: MIT. Изображения собственных питомцев перед публикацией проверяйте отдельно.

---

pet_lwt is a small standalone animated pet for Windows. Download the Windows ZIP from Releases, extract it, keep `pets` next to `pet_lwt.exe`, and run the executable. Right click the pet to choose a character, size, autostart, or exit. Drag it with the left mouse button. The tray icon can show, hide, or exit the app. Add animated GIFs to `pets` to add characters.

