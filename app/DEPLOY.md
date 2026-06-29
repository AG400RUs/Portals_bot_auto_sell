# Чеклист деплоя на Bothost

## 1. Что заливать на Bothost

Загрузи через файловый менеджер Bothost:

```
app/
  scanners/
    __init__.py
    monitor.py          ← главный скрипт
  services/
    __init__.py
    portals.py
tools/                  ← папка создастся автоматически, но создай вручную
  account.session       ← ОБЯЗАТЕЛЬНО залить вручную через файловый менеджер
requirements.txt
run_monitor.py
.env
```

⚠️  Файлы которые НЕ нужны на сервере:
- `.venv/`
- `app/scanners/mrkt_debug.py`
- `app/scanners/beautiful_monitor.py`
- `app/scanners/beautiful_numbers.py`
- `app/scanners/collection_monitor.py`
- `app/scanners/list_collections.py`
- `app/scanners/Listing monitor.py`
- `app/scanners/target_collections.py`
- `app/scanners/telegram_notifier.py`
- `app/handlers/`, `app/keyboards/`
- `main.py` (это старый бот, не монитор)

---

## 2. Переменные окружения (.env на Bothost)

Добавь в ENV на Bothost:

```
BOT_TOKEN=
ADMIN_ID=
API_ID=
API_HASH=
SESSION_NAME=account
```

SESSION_NAME должен совпадать с именем файла сессии без расширения.
Например: `account.session` → `SESSION_NAME=account`

---

## 3. Команда запуска на Bothost

```
python run_monitor.py
```

---

## 4. Загрузка .session файла

Это самый важный шаг — сессия не передаётся через Git.

1. Открой файловый менеджер Bothost
2. Перейди в папку `tools/`
3. Загрузи `account.session` вручную
4. Убедись что имя файла совпадает с `SESSION_NAME` в .env

---

## 5. Первый запуск — что ожидать в логах

```
✅ Успешный старт:
[monitor] 🚀 ПАРАЛЛЕЛЬНЫЙ МОНИТОРИНГ ЛИСТИНГОВ
[portals] 🔵 Portals Monitor запущен
[mrkt]    🟣 MRKT Monitor запущен
[portals] 📂 authData загружен из кэша  (или: 🔄 Обновляю authData)
[mrkt]    🔄 Получаю новый MRKT токен...
[mrkt]    ✅ MRKT токен сохранён

❌ Частые проблемы:
- "Сессия не найдена" → не загружен .session файл в tools/
- "Missing API_ID" → не заданы переменные окружения
- "database is locked" → два процесса запущены одновременно, останови лишний
```

---

## 6. После деплоя

- Через ~30 сек в Telegram придёт стартовое сообщение
- Если не пришло — смотри логи на Bothost
- Токены кэшируются в `tools/` и обновляются автоматически при протухании
