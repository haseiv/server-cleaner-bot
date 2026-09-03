# server-cleaner-bot

Discord-бот для **твоего** сервера: превью, потом удаление лишних каналов/ролей и кик ненужных людей. Чужие серверы не трогает (`ALLOWED_GUILD_ID`).

Команды необратимы. Для полной зачистки: `/nuke` → `confirm` = `NUKE` → кнопка **Подтвердить**.

## Настройка

1. [Discord Developer Portal](https://discord.com/developers/applications) → New Application → Bot.
2. Скопируй токен бота.
3. Privileged Gateway Intents: включи **SERVER MEMBERS INTENT**.
4. OAuth2 → URL Generator: scopes `bot` + `applications.commands`, permission **Administrator**.
5. Пригласи бота **только на свой сервер**. Роль бота поставь **выше** ролей людей, которых будешь кикать.
6. В Discord: Настройки → Расширенные → Режим разработчика. ПКМ по серверу и по себе → Копировать ID.

```
copy .env.example .env
```

Заполни `.env`:

- `DISCORD_TOKEN`
- `ALLOWED_USER_IDS` — Discord ID, кому можно вызывать команды (твой: `733202645002485772`)
- `ALLOWED_GUILD_ID` — ID сервера

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python bot.py
```

## Команды (слэш)

| Команда | Что делает |
|---|---|
| `/nuke confirm:NUKE` | Полная очистка, роль **Admin** (админка) тебе и `733202645002485772`, каналы с https://discord.gg/miamiproject |
| `/preview` | Список: сколько каналов/людей/ролей будет затронуто. Ничего не удаляет. |
| `/wipe_channels` | Удаляет каналы. Текущий канал и ID из `keep_channels` остаются. |
| `/kick_unwanted` | Кик людей без роли `keep_role`. Владелец, ты и этот бот не трогаются. |
| `/wipe_roles` | Удаляет роли, которые бот может удалить (не @everyone, не интеграционные). |

Перед удалением — кнопка **Подтвердить** (45 секунд). `/nuke` ещё требует слово `NUKE`.

Бот **не** работает на чужих серверах: только `ALLOWED_GUILD_ID`. Не создаёт спам-каналы и не шлёт рейд.
