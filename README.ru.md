# titan2-keyboard

[English](README.md) · **Русский**

Клавиатура Titan для Linux — реализация, совместимая с [Plektra](https://github.com/djbclark/plektra-djbclark)
(GPLv3) по данным и поведению. Работает отдельно от остальной оболочки Titan, в любом Wayland-композиторе
с `zwp_input_method_manager_v2` (niri, sway, Hyprland).

Изначально — пакет `titan-keyboard` из Titan DE; вынесен в отдельный репозиторий вместе с историей.

## Зависимости

Python ≥ 3.11, `evdev`, PyGObject (GTK 4, libadwaita для программы настроек), pycairo, `pywayland`,
`gtk4-layer-shell`, `wl-clipboard`. Для сборки переводов — `gettext`.

Alpine / postmarketOS: `apk add python3 py3-evdev py3-gobject3 py3-cairo py3-pywayland gtk4.0 libadwaita gtk4-layer-shell wl-clipboard`.

Демону нужен доступ к `/dev/input` (клавиатуру он захватывает) и к `/dev/uinput` (виртуальная клавиатура).

## Запуск

Из рабочего дерева:

```
LD_PRELOAD=/usr/lib/libgtk4-layer-shell.so python3 -m titan_keyboard.daemon   # демон клавиатуры
python3 -m titan_keyboard.settings                                            # «Клавиатура Titan»
python3 -m titan_keyboard.clipboard_panel                                     # панель буфера обмена
WAYLAND_DISPLAY=… python3 -m titan_keyboard.ime "текст"                       # проверка IME: вставить строку
scripts/test                                                                  # тесты
scripts/i18n                                                                  # .pot → .po → locale/*.mo
```

Пакет для Alpine: `abuild -r` в корне репозитория. Ставит `titan-keyboard` (демон), `titan-keyboard-settings`
и `.desktop` настроек; код — в `/usr/lib/titan/titan_keyboard`, данные — в `/usr/share/titan-keyboard/data`.

Настройки — `~/.config/titan/keyboard/config.toml` (перечитываются на лету, команда `reload`),
выученные слова — `~/.local/share/titan/keyboard/learned.json`, история буфера — `$XDG_DATA_HOME/titan/clipboard.json`.

## Устройство

- `titan_keyboard/engine.py` — ядро: модификаторы ⇧ и alt (тап — один символ, двойной тап — фиксация,
  удержание), alt-слой устройства, страницы sym, мульти-тап, раскладки; ⇧+пробел — следующая раскладка.
- `titan_keyboard/daemon.py` — демон: владеет физической клавиатурой, в поле ввода ведёт набор через ядро,
  вне поля отдаёт клавиши подписчикам (см. «Связь с другими программами»).
- `titan_keyboard/words.py` — подсказки слов (словари Plektra en/ru, дополнение по началу, опечатки
  на одну правку, регистр как у набранного), обучение своим словам и «следующему слову».
- `titan_keyboard/autocorrect.py` — автокоррекция по словарю опечаток Plektra (отмена ⌫ сразу после),
  автозаглавная (начало поля, после . ! ? с пробелом), правила по типу поля: в url, почте, паролях,
  PIN, числах и терминале — без подсказок, коррекции, заглавной и обучения.
- `titan_keyboard/expansion.py`, `variations.py` — сниппеты `!…`, шорткоды `:…`, вариации букв.
- `titan_keyboard/clipboard.py`, `clipboard_panel.py` — история буфера через `wl-paste --watch`
  (data-control) и её панель; записи менеджеров паролей пропускаются. Страница «буфер» — четвёртая по sym.
- `titan_keyboard/ime.py` — IME-клиент `input-method-v2`: вставка Unicode, удаление перед курсором,
  предредактирование, тип поля (пароль/PIN не подсказываются и не запоминаются).
- `titan_keyboard/bar.py`, `symview.py`, `theme.py` — полоса подсказок и страница sym на экране (layer-shell).
- `titan_keyboard/settings.py` — программа настроек (libadwaita): раскладки, паузы, помощь при наборе,
  сниппеты, свои исправления, выученные слова.
- `titan_keyboard/device/` — профиль железа Titan 2: геометрия клавиш (`layout`) и коды клавиш (`keymaps`).
  Копия `titan_device` из Titan DE; если пакет `titan-device` установлен, используется он.
- `data/plektra/` — данные Plektra без изменений (`scripts/sync-plektra <клон>`), версия в `UPSTREAM`.
- `data/dict/` — словари (`scripts/sync-dicts <клон-plektra>`): производные Leipzig Corpora Collection
  (CC-BY 3.0) через Plektra / plektra-dict (GPLv3), см. `data/dict/NOTICE.md`.
- `protocols/` — XML протоколов; `titan_keyboard/protocols/` сгенерирован `pywayland.scanner`.
- `po/` — переводы (gettext, домен `titan-keyboard`); дописывать можно в `po/<язык>-*.tsv`.

Полоса над подписями: `!сниппет`/`:шорткод` → совпадения; пока набирается слово — до 3 подсказок
(выбор тапом или броском вверх в трети сенсора, слово заменяется подсказкой с пробелом);
после пробела — предсказание следующего слова; иначе — вариации последней буквы или пунктуация.

## Связь с другими программами

Всё необязательно: без них клавиатура работает сама.

- **Сокет** `$XDG_RUNTIME_DIR/titan-keyboard.sock` (JSON по строке) — поток событий подписчикам
  (`key`, `field`, `titan`, `state`, `clipboard`) и команды (`retract`, `app`, `reload`, `pick_x`,
  `mouse`, `clipboard`). Формат — в начале `titan_keyboard/daemon.py`. В Titan DE подписчик — `titan-gestured`.
- `$XDG_RUNTIME_DIR/titan-shell.sock` — если есть `titan-shell`, ему уходит состояние раскладки и модификаторов.
- `titan_theme` — если установлен, полосы и панель буфера берут тему Titan («стекло», цвета).
- Titan DE «Настройки → Клавиатура» импортирует `titan_keyboard.config` и `titan_keyboard.settings`.

## Лицензия

GPL-3.0-or-later (`LICENSE`). Данные Plektra — GPLv3 (`data/plektra/LICENSE`), словари — см. `data/dict/NOTICE.md`.
