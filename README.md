# titan-keyboard

Клавиатура Titan для Linux — реализация, совместимая с [Plektra](https://github.com/djbclark/plektra-djbclark)
(GPLv3) по данным и поведению. Работает отдельно от остальной оболочки Titan, в любом Wayland-композиторе
с `zwp_input_method_manager_v2` (niri, sway, Hyprland).

- `titan_keyboard/engine.py` — ядро: модификаторы ⇧ и alt (тап — один символ, двойной тап — фиксация,
  удержание), alt-слой устройства, страницы sym, мульти-тап, раскладки; ⇧+пробел — следующая раскладка.
- `titan_keyboard/ime.py` — IME-клиент `input-method-v2`: вставка Unicode, удаление перед курсором,
  предредактирование, тип поля (пароль/PIN не подсказываются и не запоминаются).
- `data/plektra/` — данные Plektra без изменений (`scripts/sync-plektra <клон>`), версия в `UPSTREAM`.
- `protocols/` — XML протоколов; `titan_keyboard/protocols/` сгенерирован `pywayland.scanner`.

Проверка IME: `WAYLAND_DISPLAY=… python3 -m titan_keyboard.ime "текст"` вставит строку в поле в фокусе.
