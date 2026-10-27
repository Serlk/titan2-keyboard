# titan-keyboard

Клавиатура Titan для Linux — реализация, совместимая с [Plektra](https://github.com/djbclark/plektra-djbclark)
(GPLv3) по данным и поведению. Работает отдельно от остальной оболочки Titan, в любом Wayland-композиторе
с `zwp_input_method_manager_v2` (niri, sway, Hyprland).

- `titan_keyboard/engine.py` — ядро: модификаторы ⇧ и alt (тап — один символ, двойной тап — фиксация,
  удержание), alt-слой устройства, страницы sym, мульти-тап, раскладки; ⇧+пробел — следующая раскладка.
- `titan_keyboard/words.py` — подсказки слов (словари Plektra en/ru, дополнение по началу, опечатки
  на одну правку, регистр как у набранного), обучение своим словам и «следующему слову» —
  `~/.local/share/titan/keyboard/learned.json`.
- `titan_keyboard/autocorrect.py` — автокоррекция по словарю опечаток Plektra (отмена ⌫ сразу после),
  автозаглавная (начало поля, после . ! ? с пробелом), правила по типу поля: в url, почте, паролях,
  PIN, числах и терминале — без подсказок, коррекции, заглавной и обучения.
- `titan_keyboard/clipboard.py` — история буфера через `wl-paste --watch` (data-control); только в памяти,
  записи менеджеров паролей пропускаются. Страница «буфер» — четвёртая по sym.
- `titan_keyboard/ime.py` — IME-клиент `input-method-v2`: вставка Unicode, удаление перед курсором,
  предредактирование, тип поля (пароль/PIN не подсказываются и не запоминаются).
- `data/plektra/` — данные Plektra без изменений (`scripts/sync-plektra <клон>`), версия в `UPSTREAM`.
- `data/dict/` — словари (`scripts/sync-dicts <клон-plektra>`): производные Leipzig Corpora Collection
  (CC-BY 3.0) через Plektra / plektra-dict (GPLv3), см. `data/dict/NOTICE.md`.

Полоса над подписями: `!сниппет`/`:шорткод` → совпадения; пока набирается слово — до 3 подсказок
(выбор тапом или броском вверх в трети сенсора, слово заменяется подсказкой с пробелом);
после пробела — предсказание следующего слова; иначе — вариации последней буквы или пунктуация.
- `protocols/` — XML протоколов; `titan_keyboard/protocols/` сгенерирован `pywayland.scanner`.

Проверка IME: `WAYLAND_DISPLAY=… python3 -m titan_keyboard.ime "текст"` вставит строку в поле в фокусе.
