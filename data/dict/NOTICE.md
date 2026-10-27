# Словари titan-keyboard

Списки `*.tsv.gz` («слово<TAB>частота», самые частые слова) получены из базовых словарей
Plektra (`*_base.dict`): en — из репозитория https://github.com/djbclark/plektra-djbclark
(assets/common/dictionaries_serialized), ru — из релиза v1 https://github.com/pkb-rocks/plektra-dict
(GPLv3). Преобразование: декодирование CBOR, выбор самой частой формы слова, обрезка по частоте.

Исходные данные — производные частотных списков Leipzig Corpora Collection / Wortschatz Leipzig
(https://wortschatz.uni-leipzig.de/), CC-BY 3.0:

D. Goldhahn, T. Eckart, U. Quasthoff: *Building Large Monolingual Dictionaries at the Leipzig Corpora
Collection: From 100 to 200 Languages*. Proceedings of LREC 2012.
