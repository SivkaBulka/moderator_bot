import json
import re
import os
import time
from datetime import datetime, timedelta
import telebot
from telebot import types

# ---------- НАСТРОЙКИ ----------
TOKEN = os.getenv("BOT_TOKEN")  # Токен бота, передаётся через переменную окружения
bot = telebot.TeleBot(TOKEN)

# ---------- ХРАНИЛИЩЕ ДАННЫХ ----------
DATA_FILE = "chats_data.json"

# Структура: { chat_id (str): { "settings": {...}, "words": [...], "users": {...}, "init": bool } }
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

chats = load_data()

# ---------- КОНСТАНТЫ РАНГОВ ----------
RANKS = {
    "$": "участник",
    "*": "младший модератор",
    "**": "старший модератор",
    "***": "младший администратор",
    "****": "старший администратор",
    "#": "создатель"
}

RANK_ORDER = ["$", "*", "**", "***", "****", "#"]
RANK_NAMES = ["участник", "младший модератор", "старший модератор", "младший администратор", "старший администратор", "создатель"]

# Варианты прав назначения
RIGHT_OPTIONS = {
    1: ("#", "мунс"),
    2: ("****", "мсу"),
    3: ("****", "мунс"),
    4: ("***", "мсу"),
    5: ("***", "мунс"),
    6: ("**", "мсу"),
    7: ("**", "мунс"),
    8: ("*", "мсу"),
}

# Часовые пояса для меню
UTC_OFFSETS = [str(i) for i in range(-11, 13)]

# Словарь нормализации для фильтра слов
NORMALIZE_DICT = {
    'а': ['а', 'a', '@'],
    'б': ['б', 'b', '6'],
    'в': ['в', 'b', 'v'],
    'г': ['г'],
    'д': ['д', 'd'],
    'е': ['е', 'e'],
    'ё': ['ё'],
    'ж': ['ж'],
    'з': ['з', 'z', '3'],
    'и': ['и', 'i'],
    'й': ['й', 'i'],
    'к': ['к', 'k'],
    'л': ['л', 'l'],
    'м': ['м', 'm'],
    'н': ['н'],
    'о': ['о', 'o', '0'],
    'п': ['п', 'p'],
    'р': ['р', 'r'],
    'с': ['с', 's', 'c', '$', '€', '¢'],
    'т': ['т', 't'],
    'у': ['у', 'y', 'u', '¥'],
    'ф': ['ф', 'f'],
    'х': ['х', 'x'],
    'ц': ['ц'],
    'ч': ['ч', 'ch'],
    'ш': ['ш', 'sh'],
    'щ': ['щ', 'sch', 'sh'],
    'ъ': ['ъ', '"'],
    'ы': ['ы'],
    'ь': ['ь'],
    'э': ['э'],
    'ю': ['ю'],
    'я': ['я']
}

def normalize_text(text):
    """Приводит текст к нижнему регистру и заменяет символы на канонические."""
    text = text.lower()
    result = []
    for char in text:
        for canon, variants in NORMALIZE_DICT.items():
            if char in variants:
                result.append(canon)
                break
        else:
            result.append(char)
    return ''.join(result)

def build_pattern(word):
    """Создаёт регулярное выражение для поиска слова с учётом замен."""
    pattern_parts = []
    for canon_char in word:
        variants = NORMALIZE_DICT.get(canon_char, [canon_char])
        # Экранируем специальные символы
        escaped = [re.escape(v) for v in variants]
        pattern_parts.append('[' + ''.join(escaped) + ']')
    return ''.join(pattern_parts)

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_chat_id(message):
    return str(message.chat.id)

def get_user_rank(chat_id, user_id):
    """Возвращает ранг пользователя в чате (по умолчанию '$')."""
    chat = chats.get(chat_id, {})
    users = chat.get("users", {})
    user_data = users.get(str(user_id), {})
    return user_data.get("rank", "$")

def get_chat_creator_id(chat_id, from_api=False):
    """Возвращает Telegram user_id создателя чата. При from_api=True делает запрос к API."""
    if from_api:
        try:
            admins = bot.get_chat_administrators(chat_id)
            for admin in admins:
                if admin.status == "creator":
                    return str(admin.user.id)
        except:
            return None
    # Ищем в данных бота
    chat = chats.get(chat_id, {})
    users = chat.get("users", {})
    for uid, data in users.items():
        if data.get("rank") == "#":
            return uid
    return None

def update_creator(chat_id):
    """Обновляет создателя чата по данным Telegram (при смене владельца)."""
    api_creator = get_chat_creator_id(chat_id, from_api=True)
    if not api_creator:
        return
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    users = chat_data.setdefault("users", {})
    # Находим текущего создателя в данных и меняем на ****, если это не тот же
    for uid, data in users.items():
        if data.get("rank") == "#" and uid != api_creator:
            data["rank"] = "****"
    # Назначаем api_creator создателем
    if api_creator not in users:
        users[api_creator] = {"rank": "#", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0, "last_msg_date": ""}
    else:
        users[api_creator]["rank"] = "#"
    save_data(chats)

def get_default_settings():
    return {
        "updown_rights": "1",          # Вариант прав
        "list_word_access": "***",     # $ или ***
        "filter_mode": "off",          # off, only_del, only_warn, del_warn
        "timezone": "+3",
        "search_mode": "substring",    # substring или exact
        "anonymous": "off"             # on/off
    }

def is_group_admin(bot_member):
    """Проверяет, что бот является администратором с нужными правами."""
    if not bot_member or bot_member.status not in ["administrator", "creator"]:
        return False
    # Проверяем ключевые права
    return (bot_member.can_restrict_members and
            bot_member.can_delete_messages)

def check_bot_rights(chat_id, message=None):
    """Проверяет, что бот имеет права администратора. Возвращает True, если всё в порядке."""
    try:
        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
        if not is_group_admin(bot_member):
            if message:
                bot.reply_to(message, "Ошибка: у бота недостаточно прав")
            return False
        return True
    except:
        if message:
            bot.reply_to(message, "Ошибка: у бота недостаточно прав")
        return False

# ---------- ОБЩИЕ ПРОВЕРКИ ДЛЯ КОМАНД ----------
def require_group(func):
    """Декоратор, разрешающий команду только в группах."""
    def wrapper(message):
        if message.chat.type not in ["group", "supergroup"]:
            bot.reply_to(message, "Ошибка: команда применяется в группах")
            return
        func(message)
    return wrapper

def require_private(func):
    """Декоратор, разрешающий команду только в ЛС."""
    def wrapper(message):
        if message.chat.type != "private":
            bot.reply_to(message, "Ошибка: команда применяется в личных сообщениях боту")
            return
        func(message)
    return wrapper

def extract_username(message):
    """Извлекает username из команды (reply или аргумент)."""
    # Если ответ на сообщение
    if message.reply_to_message:
        return message.reply_to_message.from_user.username or "", message.reply_to_message.from_user.id
    # Иначе разбираем текст команды
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return None, None
    username = parts[1].strip().lstrip('@')
    # Убираем возможные лишние пробелы после ника
    username = username.split()[0]
    return username, None

def get_user_id_by_username(chat_id, username):
    """По username пытается найти user_id в чате. Возвращает (user_id, username) или None."""
    if not username:
        return None
    # Проверяем сохранённых пользователей (может быть несколько, берём любого)
    chat = chats.get(chat_id)
    if chat:
        for uid, data in chat.get("users", {}).items():
            # Ищем username в данных (можно хранить, но мы не храним username, поэтому ищем через API)
            pass
    # Лучше искать через API: получаем всех участников чата? Это дорого. Вместо этого будем получать сообщение и проверять отправителя.
    # Для простоты будем требовать reply или точный username в команде, а разрешение username -> id через get_chat_member
    try:
        # Пытаемся получить информацию о пользователе в чате
        member = bot.get_chat_member(chat_id, "@" + username)
        return str(member.user.id), username
    except:
        return None, None

# ---------- ОБРАБОТКА КОМАНД (ГРУППЫ) ----------

@bot.message_handler(commands=['start'])
@require_private
def start_private(message):
    bot.send_message(message.chat.id,
        "**Бот готов к работе!**\n"
        "Здесь вы можете использовать команды /menu и /anonim",
        parse_mode="Markdown")

@bot.message_handler(commands=['help'])
@require_group
def help_command(message):
    chat_id = get_chat_id(message)
    # Получаем настройки для динамических значков
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    updown_variant = settings.get("updown_rights", "1")
    up_icon = "#"  # по умолчанию
    down_icon = "#"
    # Определяем ранг, с которого доступны up/down
    min_rank_for_up = RIGHT_OPTIONS.get(int(updown_variant), ("#",))[0]
    # Значок для list_word
    list_word_icon = settings.get("list_word_access", "***")

    # Сокращённый список
    short_text = (
        "**Список команд**\n"
        "/help список команд\n"
        "/user информация о пользователе\n"
        "/chat информация о чате\n"
        "/ranks список администраторов\n"
        "/up повысить\n"
        "/down понизить\n"
        "/warn выдать варн\n"
        "/del_warn удалить варн\n"
        "/del_all_warn удалить все варны\n"
        "/block заблокировать\n"
        "/del_block удалить блокировку\n"
        "/list_word показать ЧС\n"
        "/add_word добавить слова в ЧС\n"
        "/del_word удалить слова из ЧС\n"
        "/setting настройки чата"
    )
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("Расширенный список", callback_data="help_expand"))
    bot.reply_to(message, short_text, parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("help_"))
def help_callback(call):
    chat_id = str(call.message.chat.id)
    # Проверка, что нажал тот, кто вызвал команду
    if call.from_user.id != call.message.reply_to_message.from_user.id:
        bot.answer_callback_query(call.id, text=f"Взаимодействовать с этим сообщением может только @{call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.first_name}", show_alert=True)
        return

    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    updown_variant = settings.get("updown_rights", "1")
    up_icon = RIGHT_OPTIONS.get(int(updown_variant), ("#",))[0]
    down_icon = up_icon  # для down тот же минимальный ранг
    list_word_icon = settings.get("list_word_access", "***")

    if call.data == "help_expand":
        text = (
            "**Список команд**\n"
            "/help список команд $\n"
            "/user [ник] информация о пользователе $\n"
            "/chat информация о чате $\n"
            "/ranks список администраторов $\n"
            f"/up [ник] повысить {up_icon}\n"
            f"/down [ник] понизить {down_icon}\n"
            "/warn [ник] выдать варн *\n"
            "/del_warn [ник] удалить варн *\n"
            "/del_all_warn [ник] удалить все варны *\n"
            "/block [ник] [время] заблокировать **\n"
            "/del_block [ник] удалить блокировку **\n"
            f"/list_word показать ЧС {list_word_icon}\n"
            "/add_word [текст] добавить слова в ЧС ***\n"
            "/del_word [текст] удалить слова из ЧС ***\n"
            "/setting настройки чата ****\n"
            "\n* значки отображают минимальный ранг для использования"
        )
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Сокращённый список", callback_data="help_collapse"))
        bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              parse_mode="Markdown", reply_markup=keyboard)
    elif call.data == "help_collapse":
        short_text = (
            "**Список команд**\n"
            "/help список команд\n"
            "/user информация о пользователе\n"
            "/chat информация о чате\n"
            "/ranks список администраторов\n"
            "/up повысить\n"
            "/down понизить\n"
            "/warn выдать варн\n"
            "/del_warn удалить варн\n"
            "/del_all_warn удалить все варны\n"
            "/block заблокировать\n"
            "/del_block удалить блокировку\n"
            "/list_word показать ЧС\n"
            "/add_word добавить слова в ЧС\n"
            "/del_word удалить слова из ЧС\n"
            "/setting настройки чата"
        )
        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton("Расширенный список", callback_data="help_expand"))
        bot.edit_message_text(short_text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                              parse_mode="Markdown", reply_markup=keyboard)
    bot.answer_callback_query(call.id)

# ---------- КОМАНДЫ /user, /chat, /ranks ----------
@bot.message_handler(commands=['user'])
@require_group
def user_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    # Получаем цель
    if message.reply_to_message:
        target = message.reply_to_message.from_user
        target_id = str(target.id)
        target_name = f"@{target.username}" if target.username else target.first_name
    elif len(message.text.split()) > 1:
        username_part = message.text.split()[1].lstrip('@')
        # Ищем пользователя
        target_id = None
        target_name = f"@{username_part}"
        # Пытаемся получить через API
        try:
            member = bot.get_chat_member(chat_id, "@" + username_part)
            target_id = str(member.user.id)
            target_name = f"@{member.user.username}" if member.user.username else member.user.first_name
        except:
            pass
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
    else:
        bot.reply_to(message, "Ошибка: неверный формат сообщения")
        return

    user_data = chats.get(chat_id, {}).get("users", {}).get(target_id, {})
    if not user_data:
        # Если данных нет, показываем пустую статистику
        user_data = {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0}

    rank = user_data.get("rank", "$")
    warns = user_data.get("warns", 0)
    blocked_until = user_data.get("blocked_until")
    msg_total = user_data.get("msg_total", 0)
    msg_30d = user_data.get("msg_last_30d", 0)
    msg_7d = user_data.get("msg_last_7d", 0)

    # Форматирование
    lines = [f"**Статистика пользователя {target_name}**"]
    lines.append(f"• Ранг: {RANKS.get(rank, 'участник')}")
    if warns > 0:
        lines.append(f"• Всего варнов: {warns}")
    else:
        lines.append("• Варны отсутствуют")
    if blocked_until:
        # Преобразуем к локальному времени с учётом часового пояса
        tz_str = chats.get(chat_id, {}).get("settings", {}).get("timezone", "+3")
        offset_hours = int(tz_str.replace("UTC", "")) if "UTC" in tz_str else int(tz_str)
        local_tz = timezone(timedelta(hours=offset_hours))
        utc_time = datetime.utcfromtimestamp(blocked_until)
        local_time = utc_time + timedelta(hours=offset_hours)
        time_str = local_time.strftime('%d.%m.%y %H:%M')
        lines.append(f"• Заблокирован до {time_str}")
    else:
        lines.append("• Блокировки отсутствуют")
    # Сообщения
    if msg_total == 0:
        lines.append("• Сообщения отсутствуют")
    else:
        lines.append(f"• Всего сообщений: {msg_total}")
        if msg_30d > 0:
            lines.append(f"• Сообщений за последние 30 дней: {msg_30d}")
        else:
            lines.append("• Сообщения отсутствуют")
        if msg_7d > 0:
            lines.append(f"• Сообщений за последние 7 дней: {msg_7d}")
        else:
            lines.append("• Сообщения отсутствуют")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=['chat'])
@require_group
def chat_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    chat_data = chats.get(chat_id, {})
    users = chat_data.get("users", {})
    settings = chat_data.get("settings", get_default_settings())

    total_msgs = sum(u.get("msg_total", 0) for u in users.values())
    msgs_30d = sum(u.get("msg_last_30d", 0) for u in users.values())
    msgs_7d = sum(u.get("msg_last_7d", 0) for u in users.values())
    participants = len(users)
    blocked_now = sum(1 for u in users.values() if u.get("blocked_until") and u["blocked_until"] > time.time())
    total_warns = sum(u.get("warns", 0) for u in users.values())
    warned_users = sum(1 for u in users.values() if u.get("warns", 0) > 0)

    anon = "да" if settings.get("anonymous") == "on" else "нет"
    list_word_access = "все" if settings.get("list_word_access") == "$" else "ограничен"
    filter_mode = settings.get("filter_mode", "off")
    filter_mode_text = {"off": "Off", "only_del": "Only Del", "only_warn": "Only Warn", "del_warn": "Del & Warn"}.get(filter_mode, filter_mode)
    search_mode = "подстрока" if settings.get("search_mode") == "substring" else "точное совпадение"
    tz = settings.get("timezone", "+3")

    lines = [
        "**Статистика чата**",
        "",
        f"• Всего сообщений: {total_msgs}",
        f"• Сообщений за последние 30 дней: {msgs_30d}",
        f"• Сообщений за последние 7 дней: {msgs_7d}",
        "",
        f"• Участников: {participants}",
        f"• На данный момент заблокировано: {blocked_now}",
        f"• Выдано {total_warns} предупреждений {warned_users} пользователям",
        "",
        f"• Отправка анонимных сообщений: {anon}",
        f"• Просмотр ЧС слов: {list_word_access}",
        f"• Режим фильтра слов: {filter_mode_text}",
        f"• Фильтр: {search_mode}",
        f"• Часовой пояс: UTC{tz}"
    ]
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

@bot.message_handler(commands=['ranks'])
@require_group
def ranks_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    users = chats.get(chat_id, {}).get("users", {})
    if not users:
        bot.reply_to(message, "**Ранги**\n• Пользователи отсутствуют", parse_mode="Markdown")
        return

    rank_lists = {"*": [], "**": [], "***": [], "****": [], "#": []}
    for uid, data in users.items():
        rank = data.get("rank", "$")
        if rank in rank_lists:
            # Получаем username
            try:
                member = bot.get_chat_member(chat_id, uid)
                uname = f"@{member.user.username}" if member.user.username else member.user.first_name
            except:
                uname = f"id{uid}"
            rank_lists[rank].append(uname)

    # Сортируем по алфавиту
    for rank in rank_lists:
        rank_lists[rank].sort()

    lines = ["**Ранги**"]
    rank_names = {
        "*": "Младшие модераторы",
        "**": "Старшие модераторы",
        "***": "Младшие администраторы",
        "****": "Старшие администраторы",
        "#": "Создатель"
    }
    for rank_key in ["*", "**", "***", "****", "#"]:
        names = "; ".join(rank_lists[rank_key]) if rank_lists[rank_key] else "отсутствуют"
        lines.append(f"• {rank_names[rank_key]}: {names}")

    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

# ---------- /up и /down ----------
@bot.message_handler(commands=['up'])
@require_group
def up_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    # Проверка прав вызывающего
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    variant = int(settings.get("updown_rights", "1"))
    min_rank, restriction = RIGHT_OPTIONS[variant]
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index(min_rank):
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    # Получаем цель
    target_id, target_uname = extract_username(message)
    if target_id:
        # из reply
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    else:
        # ищем по username
        target_id, target_uname = get_user_id_by_username(chat_id, target_uname)
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
        target_username = f"@{target_uname}"

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя повысить себя")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    target_rank = get_user_rank(chat_id, target_id)
    if RANK_ORDER.index(target_rank) >= RANK_ORDER.index("#"):
        bot.reply_to(message, "Ошибка: пользователь уже является создателем")
        return

    # Проверка ограничений
    if restriction == "мунс":
        max_rank_index = RANK_ORDER.index(caller_rank) - 1
    else:  # мсу
        max_rank_index = RANK_ORDER.index(caller_rank)

    if RANK_ORDER.index(target_rank) >= max_rank_index:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    # Повышаем
    new_rank_index = RANK_ORDER.index(target_rank) + 1
    new_rank = RANK_ORDER[new_rank_index]
    # Обновляем данные
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    user_data = chat_data["users"].setdefault(target_id, {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0})
    user_data["rank"] = new_rank
    save_data(chats)
    bot.reply_to(message, f"Пользователь {target_username} повышен до {RANKS[new_rank]}")

@bot.message_handler(commands=['down'])
@require_group
def down_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    variant = int(settings.get("updown_rights", "1"))
    min_rank, restriction = RIGHT_OPTIONS[variant]
    if RANK_ORDER.index(caller_rank) < RANK_ORDER.index(min_rank):
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    target_id, target_uname = extract_username(message)
    if target_id:
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    else:
        target_id, target_uname = get_user_id_by_username(chat_id, target_uname)
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
        target_username = f"@{target_uname}"

    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    target_rank = get_user_rank(chat_id, target_id)
    if target_rank == "$":
        bot.reply_to(message, "Ошибка: нельзя понизить участника")
        return
    if target_rank == "#":
        bot.reply_to(message, "Ошибка: нельзя понизить создателя")
        return

    # Проверка, не равны ли они (понижать равных нельзя в любом случае)
    if target_rank == caller_rank:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return

    # Понижаем
    new_rank_index = RANK_ORDER.index(target_rank) - 1
    new_rank = RANK_ORDER[new_rank_index]
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    user_data = chat_data["users"].setdefault(target_id, {"rank": target_rank, "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0})
    user_data["rank"] = new_rank
    save_data(chats)
    bot.reply_to(message, f"Пользователь {target_username} понижен до {RANKS[new_rank]}")

# ---------- ВАРНЫ ----------
@bot.message_handler(commands=['warn'])
@require_group
def warn_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    if caller_rank not in ["*", "**", "***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return
    target_id, target_uname = extract_username(message)
    if target_id:
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    else:
        target_id, target_uname = get_user_id_by_username(chat_id, target_uname)
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
        target_username = f"@{target_uname}"

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    user_data = chat_data["users"].setdefault(target_id, {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0})
    user_data["warns"] = user_data.get("warns", 0) + 1
    save_data(chats)
    bot.reply_to(message, f"**Выдан варн {target_username}**\nВсего варнов {user_data['warns']}", parse_mode="Markdown")

@bot.message_handler(commands=['del_warn'])
@require_group
def del_warn_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    if caller_rank not in ["*", "**", "***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return
    target_id, target_uname = extract_username(message)
    if target_id:
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    else:
        target_id, target_uname = get_user_id_by_username(chat_id, target_uname)
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
        target_username = f"@{target_uname}"

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    user_data = chats.get(chat_id, {}).get("users", {}).get(target_id)
    if not user_data or user_data.get("warns", 0) == 0:
        bot.reply_to(message, "Ошибка: у пользователя отсутствуют варны")
        return
    user_data["warns"] -= 1
    save_data(chats)
    bot.reply_to(message, f"**Варн {target_username} отозван**\nВсего варнов {user_data['warns']}", parse_mode="Markdown")

@bot.message_handler(commands=['del_all_warn'])
@require_group
def del_all_warn_command(message):
    # Аналогично, сбрасываем счётчик
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    if caller_rank not in ["*", "**", "***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return
    target_id, target_uname = extract_username(message)
    if target_id:
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    else:
        target_id, target_uname = get_user_id_by_username(chat_id, target_uname)
        if not target_id:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
        target_username = f"@{target_uname}"

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    user_data = chats.get(chat_id, {}).get("users", {}).get(target_id)
    if not user_data or user_data.get("warns", 0) == 0:
        bot.reply_to(message, "Ошибка: у пользователя отсутствуют варны")
        return
    user_data["warns"] = 0
    save_data(chats)
    bot.reply_to(message, f"**Все варны {target_username} отозваны**", parse_mode="Markdown")

# ---------- БЛОКИРОВКИ ----------
def parse_block_time(time_str, timezone_offset):
    """Парсит строку ДД.ММ.ГГ ЧЧ.ММ в Unix timestamp с учётом часового пояса."""
    try:
        dt = datetime.strptime(time_str, '%d.%m.%y %H.%M')
        # Переводим в UTC
        utc_dt = dt - timedelta(hours=timezone_offset)
        # Проверяем, что дата не в прошлом
        now_utc = datetime.utcnow()
        if utc_dt <= now_utc:
            return None, "Ошибка: дата в прошлом"
        # Проверяем минимальный срок (5 минут)
        if (utc_dt - now_utc).total_seconds() < 300:
            return None, "Ошибка: указанный срок менее 5 минут"
        # Проверяем максимальный срок (730 дней)
        max_date = now_utc + timedelta(days=730)
        if utc_dt > max_date:
            return None, "Ошибка: указанный срок более 730 дней"
        return int(utc_dt.timestamp()), None
    except ValueError:
        return None, "Ошибка: синтаксис времени, укажите в формате XX.XX.XX XX.XX"

@bot.message_handler(commands=['block'])
@require_group
def block_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    if caller_rank not in ["**", "***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    # Разбираем аргументы: /block <ник> <время>
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Ошибка: неверный формат сообщения")
        return
    target_part = parts[1].lstrip('@')
    time_part = parts[2]

    target_id, target_uname = None, target_part
    # Ищем пользователя по username
    try:
        member = bot.get_chat_member(chat_id, "@" + target_part)
        target_id = str(member.user.id)
        target_username = f"@{member.user.username}" if member.user.username else member.user.first_name
    except:
        bot.reply_to(message, "Ошибка: пользователь не найден")
        return

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    # Парсим время
    tz_str = chats.get(chat_id, {}).get("settings", {}).get("timezone", "+3")
    offset = int(tz_str.replace("UTC", "")) if "UTC" in tz_str else int(tz_str)
    timestamp, error = parse_block_time(time_part, offset)
    if error:
        bot.reply_to(message, error)
        return

    # Блокируем
    try:
        bot.restrict_chat_member(chat_id, int(target_id), until_date=timestamp, can_send_messages=False)
    except Exception as e:
        bot.reply_to(message, "Ошибка: у бота недостаточно прав")
        return

    # Обновляем данные
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    user_data = chat_data["users"].setdefault(target_id, {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0})
    old_block = user_data.get("blocked_until")
    user_data["blocked_until"] = timestamp
    save_data(chats)

    # Формируем ответ
    local_dt = datetime.utcfromtimestamp(timestamp) + timedelta(hours=offset)
    time_str = local_dt.strftime('%d.%m.%y %H:%M')
    if old_block and old_block > time.time():
        old_local = datetime.utcfromtimestamp(old_block) + timedelta(hours=offset)
        old_str = old_local.strftime('%d.%m.%y %H:%M')
        bot.reply_to(message, f"**Время блокировки {target_username} обновлено с {old_str} до {time_str}**", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"**{target_username} выдана блокировка до {time_str}**", parse_mode="Markdown")

@bot.message_handler(commands=['del_block'])
@require_group
def del_block_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_id = str(message.from_user.id)
    caller_rank = get_user_rank(chat_id, caller_id)
    if caller_rank not in ["**", "***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    target_id = None
    target_username = ""
    if message.reply_to_message:
        target_id = str(message.reply_to_message.from_user.id)
        target_username = f"@{message.reply_to_message.from_user.username}" if message.reply_to_message.from_user.username else message.reply_to_message.from_user.first_name
    elif len(message.text.split()) > 1:
        target_part = message.text.split()[1].lstrip('@')
        try:
            member = bot.get_chat_member(chat_id, "@" + target_part)
            target_id = str(member.user.id)
            target_username = f"@{member.user.username}" if member.user.username else member.user.first_name
        except:
            bot.reply_to(message, "Ошибка: пользователь не найден")
            return
    else:
        bot.reply_to(message, "Ошибка: неверный формат сообщения")
        return

    if target_id == caller_id:
        bot.reply_to(message, "Ошибка: нельзя применить команду к себе")
        return
    if target_id == str(bot.get_me().id):
        bot.reply_to(message, "Ошибка: нельзя применить команду к боту")
        return

    user_data = chats.get(chat_id, {}).get("users", {}).get(target_id)
    if not user_data or not user_data.get("blocked_until") or user_data["blocked_until"] <= time.time():
        bot.reply_to(message, "Ошибка: пользователь не заблокирован")
        return

    # Разблокируем
    try:
        bot.restrict_chat_member(chat_id, int(target_id), can_send_messages=True, can_send_media_messages=True,
                                 can_send_other_messages=True, can_add_web_page_previews=True)
    except Exception as e:
        bot.reply_to(message, "Ошибка: у бота недостаточно прав")
        return

    user_data["blocked_until"] = None
    save_data(chats)
    bot.reply_to(message, f"**Все блокировки {target_username} отменены**", parse_mode="Markdown")

# ---------- ФИЛЬТР СЛОВ ----------
@bot.message_handler(commands=['list_word'])
@require_group
def list_word_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    access = settings.get("list_word_access", "***")
    caller_rank = get_user_rank(chat_id, str(message.from_user.id))
    if access != "$" and RANK_ORDER.index(caller_rank) < RANK_ORDER.index("***"):
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    words = chats.get(chat_id, {}).get("words", [])
    page = 1
    # Пагинация
    items_per_page = 32
    total_pages = max(1, (len(words) + items_per_page - 1) // items_per_page) if words else 1
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_words = words[start:end]

    text = f"**Чёрный список слов, страница {page}/{total_pages}:**\n"
    if page_words:
        for w in page_words:
            text += f"• {w}\n"
    else:
        text += "• Список пуст"

    keyboard = types.InlineKeyboardMarkup()
    if total_pages > 1:
        # первая страница - только >
        if page == 1 and total_pages > 1:
            keyboard.add(types.InlineKeyboardButton(">", callback_data=f"listword_{chat_id}_{page + 1}"))
        elif page == total_pages:
            keyboard.add(types.InlineKeyboardButton("<", callback_data=f"listword_{chat_id}_{page - 1}"))
        else:
            keyboard.add(types.InlineKeyboardButton("<", callback_data=f"listword_{chat_id}_{page - 1}"),
                         types.InlineKeyboardButton(">", callback_data=f"listword_{chat_id}_{page + 1}"))
    bot.reply_to(message, text, parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("listword_"))
def list_word_callback(call):
    # Проверяем, что нажал автор команды
    if call.from_user.id != call.message.reply_to_message.from_user.id:
        bot.answer_callback_query(call.id, text=f"Взаимодействовать с этим сообщением может только @{call.message.reply_to_message.from_user.username or call.message.reply_to_message.from_user.first_name}", show_alert=True)
        return

    data = call.data.split("_")
    chat_id = data[1]
    page = int(data[2])
    words = chats.get(chat_id, {}).get("words", [])
    items_per_page = 32
    total_pages = max(1, (len(words) + items_per_page - 1) // items_per_page) if words else 1
    start = (page - 1) * items_per_page
    end = start + items_per_page
    page_words = words[start:end]

    text = f"**Чёрный список слов, страница {page}/{total_pages}:**\n"
    if page_words:
        for w in page_words:
            text += f"• {w}\n"
    else:
        text += "• Список пуст"

    keyboard = types.InlineKeyboardMarkup()
    if total_pages > 1:
        if page == 1:
            keyboard.add(types.InlineKeyboardButton(">", callback_data=f"listword_{chat_id}_{page + 1}"))
        elif page == total_pages:
            keyboard.add(types.InlineKeyboardButton("<", callback_data=f"listword_{chat_id}_{page - 1}"))
        else:
            keyboard.add(types.InlineKeyboardButton("<", callback_data=f"listword_{chat_id}_{page - 1}"),
                         types.InlineKeyboardButton(">", callback_data=f"listword_{chat_id}_{page + 1}"))
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id,
                          parse_mode="Markdown", reply_markup=keyboard)
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['add_word'])
@require_group
def add_word_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_rank = get_user_rank(chat_id, str(message.from_user.id))
    if caller_rank not in ["***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    # Слова после команды, разделённые новой строкой
    lines = message.text.split('\n', 1)
    if len(lines) < 2 or not lines[1].strip():
        bot.reply_to(message, "Ошибка: неверный формат сообщения")
        return
    new_words_raw = lines[1].strip().split('\n')
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    existing_words = chat_data["words"]
    added = []
    not_added = []
    for raw_word in new_words_raw:
        raw_word = raw_word.strip()
        if not raw_word:
            continue
        normalized = normalize_text(raw_word)
        if normalized in existing_words:
            not_added.append(raw_word)
        else:
            existing_words.append(normalized)
            added.append(raw_word)

    save_data(chats)
    response = ""
    if added:
        response += "**Успешно добавлено:**\n" + "\n".join(added) + "\n"
    if not_added:
        response += "**Невозможно добавить, уже находится в списке:**\n" + "\n".join(not_added)
    if not response:
        response = "Ошибка: неверный формат сообщения"
    bot.reply_to(message, response, parse_mode="Markdown")

@bot.message_handler(commands=['del_word'])
@require_group
def del_word_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_rank = get_user_rank(chat_id, str(message.from_user.id))
    if caller_rank not in ["***", "****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return

    lines = message.text.split('\n', 1)
    if len(lines) < 2 or not lines[1].strip():
        bot.reply_to(message, "Ошибка: неверный формат сообщения")
        return
    del_words_raw = lines[1].strip().split('\n')
    chat_data = chats.get(chat_id)
    if not chat_data:
        bot.reply_to(message, "Ошибка: список слов пуст")
        return
    existing_words = chat_data.get("words", [])
    deleted = []
    not_found = []
    for raw_word in del_words_raw:
        raw_word = raw_word.strip()
        if not raw_word:
            continue
        normalized = normalize_text(raw_word)
        if normalized in existing_words:
            existing_words.remove(normalized)
            deleted.append(raw_word)
        else:
            not_found.append(raw_word)

    save_data(chats)
    response = ""
    if deleted:
        response += "**Успешно удалено:**\n" + "\n".join(deleted) + "\n"
    if not_found:
        response += "**Невозможно удалить, отсутствует в списке:**\n" + "\n".join(not_found)
    if not response:
        response = "Ошибка: неверный формат сообщения"
    bot.reply_to(message, response, parse_mode="Markdown")

# ---------- НАСТРОЙКИ (/setting) ----------
@bot.message_handler(commands=['setting'])
@require_group
def setting_command(message):
    chat_id = get_chat_id(message)
    if not check_bot_rights(chat_id, message):
        return
    caller_rank = get_user_rank(chat_id, str(message.from_user.id))
    if caller_rank not in ["****", "#"]:
        bot.reply_to(message, "Ошибка: недостаточно прав")
        return
    show_settings_main(message.chat.id, chat_id, message.message_id + 1)  # ответим новым сообщением
    # На самом деле reply не используем, чтобы не путаться с кнопками, отправим новое

def show_settings_main(chat_id, data_chat_id, reply_to=None):
    settings = chats.get(data_chat_id, {}).get("settings", get_default_settings())
    list_word_access = settings.get("list_word_access", "***")
    search_mode = "подстрока" if settings.get("search_mode") == "substring" else "точное совпадение"
    anon = "Вкл" if settings.get("anonymous") == "on" else "Выкл"
    filter_mode = settings.get("filter_mode", "off")
    filter_text = {"off": "Off", "only_del": "Only Del", "only_warn": "Only Warn", "del_warn": "Del & Warn"}.get(filter_mode, "Off")
    tz = settings.get("timezone", "+3")

    text = "**Настройки чата**"
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    # Ряд 1: list_word и search_mode
    btn_list = types.InlineKeyboardButton(
        f"Доступ /list_word {'$' if list_word_access == '$' else '***'}",
        callback_data=f"set_toggle_listword|{data_chat_id}"
    )
    btn_search = types.InlineKeyboardButton(
        f"Фильтр: {search_mode}",
        callback_data=f"set_toggle_search|{data_chat_id}"
    )
    keyboard.add(btn_list, btn_search)
    # Ряд 2: анонимный режим
    btn_anon = types.InlineKeyboardButton(
        f"Анонимный режим: {anon}",
        callback_data=f"set_toggle_anon|{data_chat_id}"
    )
    keyboard.add(btn_anon)
    # Ряд 3: права up/down и часовой пояс
    btn_rights = types.InlineKeyboardButton(
        "Права /up и /down",
        callback_data=f"set_rights_menu|{data_chat_id}"
    )
    btn_tz = types.InlineKeyboardButton(
        f"Часовой пояс UTC{tz}",
        callback_data=f"set_tz_menu|{data_chat_id}"
    )
    keyboard.add(btn_rights, btn_tz)
    # Ряд 4: режим фильтра
    btn_filter = types.InlineKeyboardButton(
        "Режим фильтра",
        callback_data=f"set_filter_menu|{data_chat_id}"
    )
    keyboard.add(btn_filter)

    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def setting_callback(call):
    data = call.data.split("|")
    action = data[0]
    chat_id = data[1]
    # Проверка прав
    caller_rank = get_user_rank(chat_id, str(call.from_user.id))
    if caller_rank not in ["****", "#"]:
        bot.answer_callback_query(call.id, text="Недостаточно прав", show_alert=True)
        return
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())

    if action == "set_toggle_listword":
        current = settings.get("list_word_access", "***")
        new_val = "$" if current != "$" else "***"
        settings["list_word_access"] = new_val
        save_data(chats)
        bot.answer_callback_query(call.id, text=f"Режим Доступ /list_word {'для всех' if new_val == '$' else 'ограничен'} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_toggle_search":
        current = settings.get("search_mode", "substring")
        new_val = "exact" if current == "substring" else "substring"
        settings["search_mode"] = new_val
        save_data(chats)
        bot.answer_callback_query(call.id, text=f"Режим Фильтр: {'подстрока' if new_val == 'substring' else 'точное совпадение'} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_toggle_anon":
        current = settings.get("anonymous", "off")
        new_val = "on" if current == "off" else "off"
        settings["anonymous"] = new_val
        save_data(chats)
        bot.answer_callback_query(call.id, text=f"Режим Анонимный режим {'вкл' if new_val == 'on' else 'выкл'} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_rights_menu":
        # Подменю выбора варианта прав
        variant = int(settings.get("updown_rights", "1"))
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        btns = []
        for i in range(1, 9):
            label = str(i)
            if i == variant:
                label = "🔴 " + label
            btns.append(types.InlineKeyboardButton(label, callback_data=f"set_rights_set|{chat_id}|{i}"))
        keyboard.add(*btns)
        keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=f"set_back|{chat_id}"))
        bot.edit_message_text("Выберите вариант прав для /up и /down:", chat_id=call.message.chat.id,
                              message_id=call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
    elif action == "set_rights_set":
        variant = int(data[2])
        settings["updown_rights"] = str(variant)
        save_data(chats)
        bot.answer_callback_query(call.id, text=f"Режим Вариант {variant} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_tz_menu":
        current_tz = settings.get("timezone", "+3")
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        btns = []
        for tz in UTC_OFFSETS:
            label = f"UTC{tz}"
            if tz == current_tz.replace("UTC", "").replace("+", ""):  # грубо
                label = "🔴 " + label
            btns.append(types.InlineKeyboardButton(label, callback_data=f"set_tz_set|{chat_id}|{tz}"))
        keyboard.add(*btns)
        keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=f"set_back|{chat_id}"))
        bot.edit_message_text("Выберите часовой пояс:", chat_id=call.message.chat.id,
                              message_id=call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
    elif action == "set_tz_set":
        tz = data[2]
        settings["timezone"] = f"+{tz}" if not tz.startswith('-') else tz
        save_data(chats)
        bot.answer_callback_query(call.id, text=f"Режим Часовой пояс UTC{tz} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_filter_menu":
        current_filter = settings.get("filter_mode", "off")
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        filters = [("off", "Off"), ("del_warn", "Del & Warn"), ("only_del", "Only Del"), ("only_warn", "Only Warn")]
        btns = []
        for f_val, f_text in filters:
            label = f_text
            if f_val == current_filter:
                label = "🔴 " + label
            btns.append(types.InlineKeyboardButton(label, callback_data=f"set_filter_set|{chat_id}|{f_val}"))
        keyboard.add(*btns)
        keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=f"set_back|{chat_id}"))
        bot.edit_message_text("Выберите режим фильтра:", chat_id=call.message.chat.id,
                              message_id=call.message.message_id, reply_markup=keyboard)
        bot.answer_callback_query(call.id)
    elif action == "set_filter_set":
        f_val = data[2]
        if settings.get("filter_mode") == f_val:
            bot.answer_callback_query(call.id, text="Режим уже выбран", show_alert=True)
            return
        settings["filter_mode"] = f_val
        save_data(chats)
        filter_text = {"off": "Off", "del_warn": "Del & Warn", "only_del": "Only Del", "only_warn": "Only Warn"}[f_val]
        bot.answer_callback_query(call.id, text=f"Режим {filter_text} установлен")
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
    elif action == "set_back":
        show_settings_main(call.message.chat.id, chat_id, call.message.message_id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id)

# ---------- ЛИЧНЫЕ СООБЩЕНИЯ: /menu и /anonim ----------
@bot.message_handler(commands=['menu'])
@require_private
def menu_command(message):
    user_id = message.from_user.id
    common_chats = []
    for chat_id_str, chat_data in chats.items():
        try:
            member = bot.get_chat_member(int(chat_id_str), user_id)
            if member:
                common_chats.append((chat_id_str, bot.get_chat(int(chat_id_str)).title))
        except:
            pass
    if not common_chats:
        bot.send_message(message.chat.id, "Нет общих чатов")
        return
    common_chats.sort(key=lambda x: x[1].lower())  # по алфавиту
    keyboard = types.InlineKeyboardMarkup()
    for cid, ctitle in common_chats:
        keyboard.add(types.InlineKeyboardButton(ctitle, callback_data=f"menu_chat|{cid}"))
    bot.send_message(message.chat.id, "Выберите чат:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_chat"))
def menu_chat_callback(call):
    chat_id = call.data.split("|")[1]
    # Показать действия
    keyboard = types.InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        types.InlineKeyboardButton("My Stats", callback_data=f"menu_action|{chat_id}|mystats"),
        types.InlineKeyboardButton("Chat", callback_data=f"menu_action|{chat_id}|chat")
    )
    keyboard.add(
        types.InlineKeyboardButton("Ranks", callback_data=f"menu_action|{chat_id}|ranks"),
        types.InlineKeyboardButton("List Word", callback_data=f"menu_action|{chat_id}|listword")
    )
    keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=f"menu_back"))
    # Проверим, доступен ли list_word
    settings = chats.get(chat_id, {}).get("settings", get_default_settings())
    access = settings.get("list_word_access", "***")
    user_rank = get_user_rank(chat_id, str(call.from_user.id))
    if access == "$" or RANK_ORDER.index(user_rank) >= RANK_ORDER.index("***"):
        # Можно
        pass
    else:
        # Меняем кнопку List Word на красную и делаем callback с ошибкой
        # Для простоты оставим ту же кнопку, но при нажатии проверим внутри
        # На самом деле проще пересоздать клавиатуру с учётом прав
        keyboard = types.InlineKeyboardMarkup(row_width=2)
        keyboard.add(
            types.InlineKeyboardButton("My Stats", callback_data=f"menu_action|{chat_id}|mystats"),
            types.InlineKeyboardButton("Chat", callback_data=f"menu_action|{chat_id}|chat")
        )
        keyboard.add(
            types.InlineKeyboardButton("Ranks", callback_data=f"menu_action|{chat_id}|ranks"),
            types.InlineKeyboardButton("🔴 List Word", callback_data=f"menu_action_denied|{chat_id}")
        )
        keyboard.add(types.InlineKeyboardButton("← Назад", callback_data=f"menu_back"))
    bot.edit_message_text("Выберите действие:", chat_id=call.message.chat.id, message_id=call.message.message_id,
                          reply_markup=keyboard)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_action_denied"))
def menu_action_denied(call):
    bot.answer_callback_query(call.id, text="Просмотр недоступен", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("menu_action"))
def menu_action_callback(call):
    _, chat_id, action = call.data.split("|")
    if action == "mystats":
        # Показываем свою статистику
        user_id = str(call.from_user.id)
        user_data = chats.get(chat_id, {}).get("users", {}).get(user_id, {})
        if not user_data:
            user_data = {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0}
        rank = user_data.get("rank", "$")
        warns = user_data.get("warns", 0)
        blocked_until = user_data.get("blocked_until")
        # Форматирование (аналогично /user)
        lines = [f"**Статистика пользователя @{call.from_user.username or call.from_user.first_name}**"]
        lines.append(f"• Ранг: {RANKS.get(rank, 'участник')}")
        if warns > 0:
            lines.append(f"• Всего варнов: {warns}")
        else:
            lines.append("• Варны отсутствуют")
        if blocked_until and blocked_until > time.time():
            tz_str = chats.get(chat_id, {}).get("settings", {}).get("timezone", "+3")
            offset = int(tz_str.replace("UTC", "")) if "UTC" in tz_str else int(tz_str)
            local_dt = datetime.utcfromtimestamp(blocked_until) + timedelta(hours=offset)
            time_str = local_dt.strftime('%d.%m.%y %H:%M')
            lines.append(f"• Заблокирован до {time_str}")
        else:
            lines.append("• Блокировки отсутствуют")
        # Сообщения
        msg_total = user_data.get("msg_total", 0)
        msg_30d = user_data.get("msg_last_30d", 0)
        msg_7d = user_data.get("msg_last_7d", 0)
        if msg_total == 0:
            lines.append("• Сообщения отсутствуют")
        else:
            lines.append(f"• Всего сообщений: {msg_total}")
            lines.append(f"• Сообщений за последние 30 дней: {msg_30d}")
            lines.append(f"• Сообщений за последние 7 дней: {msg_7d}")
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode="Markdown")
    elif action == "chat":
        # Аналогично /chat но отправим в ЛС
        chat_data = chats.get(chat_id, {})
        users = chat_data.get("users", {})
        settings = chat_data.get("settings", get_default_settings())
        # заполняем статистику
        total_msgs = sum(u.get("msg_total", 0) for u in users.values())
        msgs_30d = sum(u.get("msg_last_30d", 0) for u in users.values())
        msgs_7d = sum(u.get("msg_last_7d", 0) for u in users.values())
        participants = len(users)
        blocked_now = sum(1 for u in users.values() if u.get("blocked_until") and u["blocked_until"] > time.time())
        total_warns = sum(u.get("warns", 0) for u in users.values())
        warned_users = sum(1 for u in users.values() if u.get("warns", 0) > 0)
        anon = "да" if settings.get("anonymous") == "on" else "нет"
        list_word_access = "все" if settings.get("list_word_access") == "$" else "ограничен"
        filter_mode = settings.get("filter_mode", "off")
        filter_mode_text = {"off": "Off", "only_del": "Only Del", "only_warn": "Only Warn", "del_warn": "Del & Warn"}.get(filter_mode, filter_mode)
        search_mode = "подстрока" if settings.get("search_mode") == "substring" else "точное совпадение"
        tz = settings.get("timezone", "+3")
        lines = [
            "**Статистика чата**",
            "",
            f"• Всего сообщений: {total_msgs}",
            f"• Сообщений за последние 30 дней: {msgs_30d}",
            f"• Сообщений за последние 7 дней: {msgs_7d}",
            "",
            f"• Участников: {participants}",
            f"• На данный момент заблокировано: {blocked_now}",
            f"• Выдано {total_warns} предупреждений {warned_users} пользователям",
            "",
            f"• Отправка анонимных сообщений: {anon}",
            f"• Просмотр ЧС слов: {list_word_access}",
            f"• Режим фильтра слов: {filter_mode_text}",
            f"• Фильтр: {search_mode}",
            f"• Часовой пояс: UTC{tz}"
        ]
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode="Markdown")
    elif action == "ranks":
        # аналог /ranks
        rank_lists = {"*": [], "**": [], "***": [], "****": [], "#": []}
        for uid, data in chats.get(chat_id, {}).get("users", {}).items():
            rank = data.get("rank", "$")
            if rank in rank_lists:
                try:
                    member = bot.get_chat_member(int(chat_id), int(uid))
                    uname = f"@{member.user.username}" if member.user.username else member.user.first_name
                except:
                    uname = f"id{uid}"
                rank_lists[rank].append(uname)
        for r in rank_lists:
            rank_lists[r].sort()
        lines = ["**Ранги**"]
        rank_names = {
            "*": "Младшие модераторы",
            "**": "Старшие модераторы",
            "***": "Младшие администраторы",
            "****": "Старшие администраторы",
            "#": "Создатель"
        }
        for rank_key in ["*", "**", "***", "****", "#"]:
            names = "; ".join(rank_lists[rank_key]) if rank_lists[rank_key] else "отсутствуют"
            lines.append(f"• {rank_names[rank_key]}: {names}")
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode="Markdown")
    elif action == "listword":
        # Пагинация неудобна, выведем первую страницу или можно без кнопок для ЛС
        words = chats.get(chat_id, {}).get("words", [])
        text = "**Чёрный список слов**\n" + "\n".join(f"• {w}" for w in words) if words else "Список пуст"
        bot.send_message(call.message.chat.id, text, parse_mode="Markdown")
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "menu_back")
def menu_back_callback(call):
    # Возвращаемся к списку чатов
    user_id = call.from_user.id
    common_chats = []
    for chat_id_str, chat_data in chats.items():
        try:
            member = bot.get_chat_member(int(chat_id_str), user_id)
            if member:
                common_chats.append((chat_id_str, bot.get_chat(int(chat_id_str)).title))
        except:
            pass
    common_chats.sort(key=lambda x: x[1].lower())
    keyboard = types.InlineKeyboardMarkup()
    for cid, ctitle in common_chats:
        keyboard.add(types.InlineKeyboardButton(ctitle, callback_data=f"menu_chat|{cid}"))
    bot.edit_message_text("Выберите чат:", chat_id=call.message.chat.id, message_id=call.message.message_id,
                          reply_markup=keyboard)
    bot.answer_callback_query(call.id)

# ---------- /anonim ----------
@bot.message_handler(commands=['anonim'])
@require_private
def anonim_command(message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Ошибка: неверный формат сообщения")
        return
    text = parts[1]
    user_id = message.from_user.id
    common_chats = []
    for chat_id_str, chat_data in chats.items():
        try:
            member = bot.get_chat_member(int(chat_id_str), user_id)
            if member:
                settings = chat_data.get("settings", get_default_settings())
                anon = settings.get("anonymous", "off")
                common_chats.append((chat_id_str, bot.get_chat(int(chat_id_str)).title, anon))
        except:
            pass
    if not common_chats:
        bot.send_message(message.chat.id, "Нет общих чатов")
        return
    common_chats.sort(key=lambda x: x[1].lower())
    keyboard = types.InlineKeyboardMarkup()
    for cid, ctitle, anon in common_chats:
        if anon == "on":
            keyboard.add(types.InlineKeyboardButton(ctitle, callback_data=f"anon_confirm|{cid}|{text[:50]}"))  # ограничим длину
        else:
            keyboard.add(types.InlineKeyboardButton(f"🔴 {ctitle}", callback_data=f"anon_denied|{ctitle}"))
    bot.send_message(message.chat.id, "Выберите чат для анонимного сообщения:", reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data.startswith("anon_denied"))
def anon_denied(call):
    chat_title = call.data.split("|")[1]
    bot.answer_callback_query(call.id, text=f"Функция недоступна в {chat_title}", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("anon_confirm"))
def anon_confirm_callback(call):
    _, chat_id, text_preview = call.data.split("|")
    # Ищем полный текст из сообщения? Мы сохранили только первые 50 символов. Лучше хранить временно.
    # Для упрощения: текст передаётся в callback_data? Может быть длинный, но максимум 64 байта.
    # Обходной путь: сохранять в словарь. Но для MVP допустим, что текст короткий.
    # Отправим подтверждение
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(
        types.InlineKeyboardButton("Да", callback_data=f"anon_send|{chat_id}|{call.message.reply_to_message.text.split(maxsplit=1)[1][:100]}"),
        types.InlineKeyboardButton("Отмена", callback_data="anon_cancel")
    )
    # На самом деле нужно получить исходный текст. В реальном коде лучше использовать состояние.
    # Пока используем упрощённый механизм: текст берём из исходного сообщения, которое reply
    bot.edit_message_text(
        f"**Вы действительно хотите отправить в чат анонимное сообщение**\n> {call.message.reply_to_message.text.split(maxsplit=1)[1]}",
        chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode="Markdown", reply_markup=keyboard)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("anon_send"))
def anon_send(call):
    _, chat_id, text = call.data.split("|", 2)
    # Отправляем в чат
    bot.send_message(int(chat_id), f"**Новое анонимное сообщение**\n{text}", parse_mode="Markdown")
    bot.edit_message_text("Сообщение отправлено", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "anon_cancel")
def anon_cancel(call):
    # Вернуться к списку чатов
    bot.edit_message_text("Отправка отменена", chat_id=call.message.chat.id, message_id=call.message.message_id)
    bot.answer_callback_query(call.id)

# ---------- ФИЛЬТР СООБЩЕНИЙ И СЧЁТЧИКИ ----------
@bot.message_handler(func=lambda message: True, content_types=['text', 'photo', 'video', 'document', 'audio', 'sticker', 'voice', 'contact', 'location', 'venue'])
def message_counter_and_filter(message):
    # Игнорируем личные сообщения (уже обработаны командами)
    if message.chat.type not in ["group", "supergroup"]:
        return
    chat_id = get_chat_id(message)
    user_id = str(message.from_user.id)

    # Проверка прав бота (при каждом сообщении)
    if not check_bot_rights(chat_id, message):
        return

    # Обновляем создателя (если сменился владелец)
    update_creator(chat_id)

    # Инициализация данных чата, если надо
    chat_data = chats.setdefault(chat_id, {"settings": get_default_settings(), "words": [], "users": {}, "init": False})
    if not chat_data.get("init"):
        # При первой активности в чате отправляем приветствие
        chat_data["init"] = True
        save_data(chats)
        bot.send_message(chat_id,
            "**Бот готов к работе!**\n"
            "Для поиска команд используйте /help\n"
            "Для настройки чата используйте /setting\n"
            "Используйте /up чтобы назначить админов",
            parse_mode="Markdown")
        return  # Пропускаем фильтр для первого сообщения? Нет, просто инициализируем и идём дальше

    # Увеличиваем счётчики сообщений пользователя
    user_data = chat_data["users"].setdefault(user_id, {"rank": "$", "warns": 0, "blocked_until": None, "msg_total": 0, "msg_last_30d": 0, "msg_last_7d": 0, "last_msg_date": ""})
    user_data["msg_total"] = user_data.get("msg_total", 0) + 1
    # Обновление окон за 30 и 7 дней
    now = datetime.utcnow()
    last_date_str = user_data.get("last_msg_date", "")
    if last_date_str:
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
        # Если прошло больше 30 дней, сбрасываем 30-дневный счётчик
        if (now - last_date).days >= 30:
            user_data["msg_last_30d"] = 0
        # Если прошло больше 7 дней, сбрасываем 7-дневный
        if (now - last_date).days >= 7:
            user_data["msg_last_7d"] = 0
    user_data["msg_last_30d"] = user_data.get("msg_last_30d", 0) + 1
    user_data["msg_last_7d"] = user_data.get("msg_last_7d", 0) + 1
    user_data["last_msg_date"] = now.strftime("%Y-%m-%d")
    save_data(chats)

    # Фильтр слов (только для текстовых сообщений)
    settings = chat_data.get("settings", get_default_settings())
    filter_mode = settings.get("filter_mode", "off")
    if filter_mode == "off" or not message.text:
        return

    words = chat_data.get("words", [])
    if not words:
        return

    text_to_check = normalize_text(message.text)
    search_mode = settings.get("search_mode", "substring")
    found = False
    for word in words:
        if search_mode == "substring":
            pattern = build_pattern(word)
            if re.search(pattern, text_to_check):
                found = True
                break
        else:  # exact
            pattern = r'\b' + build_pattern(word) + r'\b'
            if re.search(pattern, text_to_check):
                found = True
                break

    if not found:
        return

    # Применяем санкции
    # Удаление
    if filter_mode in ("only_del", "del_warn"):
        try:
            bot.delete_message(chat_id, message.message_id)
        except:
            pass

    # Варн
    if filter_mode in ("only_warn", "del_warn"):
        user_data["warns"] = user_data.get("warns", 0) + 1
        save_data(chats)
        # Уведомление в чат? Не требуется, просто счётчик увеличивается
        # Можно уведомить модераторов, но не будем усложнять

    # Если комбинированный режим, сообщение уже удалено, варн выдан

# ---------- ЗАПУСК БОТА ----------
if __name__ == "__main__":
    print("Бот запущен...")
    # Проверяем, что все чаты инициализированы (при необходимости)
    bot.infinity_polling()
