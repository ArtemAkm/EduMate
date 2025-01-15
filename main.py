import telebot
from telebot import types
import re
import sqlite3
import atexit
import pytz
import datetime
from datetime import datetime, timedelta, date
import re
import schedule
import json
import time
from telebot.types import BotCommand, Message, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
import threading
import transliterate
import random
import os
import shutil

import logging
import sys
import traceback

from chat_gpt import ask_gpt_with_timeout
models = ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

# error_log_file = r'C:\Users\konstpm\Desktop\Beneki\launcher\bot_error_log.txt'
# logging.basicConfig(filename=error_log_file, level=logging.ERROR)

# class CustomExceptionHook:
#     def __init__(self):
#         sys.excepthook = self.log_uncaught_exceptions

#     def log_uncaught_exceptions(self, ex_cls, ex, tb):
#         if tb:
#             logging.error(''.join(traceback.format_tb(tb)))
#             logging.error('{0}: {1}'.format(ex_cls.__name__, ex))
#         else:
#             pass

# Создаем экземпляр нашего обработчика
# CustomExceptionHook()

with open('config.json', 'r') as config_file:
    config = json.load(config_file)

timezone = pytz.timezone('Europe/Kiev')

conn = sqlite3.connect('users.db', check_same_thread=False)
cursor = conn.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    birthday TEXT,
    username TEXT
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_of_week TEXT,
    lesson_number INTEGER,
    subject TEXT,
    start_time TEXT,
    end_time TEXT,
    command TEXT,
    reminded INTEGER DEFAULT 0
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS homework (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT,
    homework TEXT,
    photo_ids TEXT,
    date TEXT
)
''')
conn.commit()


cursor.execute('''
CREATE TABLE IF NOT EXISTS important_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT,
    end_date TEXT,
    event_text TEXT
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    message_id INTEGER,
    has_buttons INTEGER DEFAULT 0
)
''')
conn.commit()

cursor.execute('''
    CREATE TABLE IF NOT EXISTS homework_state (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER,
        subject TEXT,
        homework TEXT,
        photo_ids TEXT,
        step TEXT
    )
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS banned_users (
    user_id INTEGER PRIMARY KEY,
    ban_end_time TIMESTAMP,
    ban_reason TEXT
)
''')
conn.commit()



bot = telebot.TeleBot(config['api_token'], use_class_middlewares = True) 

commands = [
    BotCommand("start", "Начать или продолжить общение"),
    BotCommand("help", "Показать список доступных команд"),
    BotCommand("get_info", "Получить информацию о себе"),
    BotCommand("register", "Повторная регистрация"),
    BotCommand("homework", "Записать домашнее задание"),
    BotCommand("message_admin", "Отправить сообщение админу"),
    BotCommand("info", "Информация о боте")
]

admin_commands = [
    BotCommand("monday", "Заполнить расписание на понедельник"),
    BotCommand("tuesday", "Заполнить расписание на вторник"),
    BotCommand("wednesday", "Заполнить расписание на среду"),
    BotCommand("thursday", "Заполнить расписание на четверг"),
    BotCommand("friday", "Заполнить расписание на пятницу"),
    BotCommand("add_event", "Создать важное событие"),
    BotCommand("delete_event", "Удалить важное событие"),
    BotCommand("list_events", "Список важных событий"),
    BotCommand("list_users", "Получить список пользователей"),
    BotCommand("edit_lesson", "Изменить урок по дню и номеру урока"),
    BotCommand("delete_last_lesson", "Удалить последний урок на день"),
    BotCommand("add_lesson", "Добавить новый урок в конец дня")
]

god_commands = [
    BotCommand("clear_db", "Полная очистка бд"),
    BotCommand("delete_homework", "Удалить поле домашки из базы данных"),
    BotCommand("show_homework", "Вывод БД домашних заданий"),
    BotCommand("broadcast_message", "Разослать сообщение всем пользователям"),
    BotCommand("message_user", "Отправить сообщение конкретному пользователю")
]

admin_ids = config['admin_ids']
god_id = config['god_id']

@bot.message_handler(commands=['unban'])
def unban_user(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Введите ID пользователя, которого хотите разбанить.")
        bot.register_next_step_handler(message, perform_unban)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

def perform_unban(message):
    try:
        user_id = int(message.text)
        cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        
        if result:
            cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            conn.commit()
            bot.send_message(message.chat.id, f"✅Пользователь был успешно разбанен.")
            text = "👮 Бан был снят\n\nТеперь тебе доступен полный функционал бота. Напиши /help что-бы посмотреть доступные команды"
            show_schedule_buttons(user_id, text)
        else:
            bot.send_message(message.chat.id, "Пользователь с таким ID не найден в списке забаненных.")
    except ValueError:
        bot.send_message(message.chat.id, "Введите корректный ID пользователя.")

@bot.message_handler(commands=['ban'])
def start_ban_process(message):
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id, "Введите ID пользователя, которого хотите забанить.")
        bot.register_next_step_handler(message, get_user_id)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

def get_user_id(message):
    try:
        user_id = int(message.text)
        if user_id == message.chat.id:
            bot.send_message(message.chat.id, "❌Нельзя забанить самого себя")
            return
        if user_id == god_id:
            bot.send_message(message.chat.id, "❌Нельзя забанить того, кто выше тебя по уровню")
            bot.send_message(god_id, f"👮Тебя пытался забанить @{message.from_user.username}")
            return
        cursor.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,))
        if cursor.fetchone():
            bot.send_message(message.chat.id, "❌Этот пользователь уже забанен")
            return
        cursor.execute("SELECT name, username FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        if result:
            name, username = result
            markup = types.InlineKeyboardMarkup()
            confirm_button = types.InlineKeyboardButton("Да", callback_data=f"confirm_ban_{user_id}")
            cancel_button = types.InlineKeyboardButton("Нет", callback_data="cancel_ban")
            markup.add(confirm_button, cancel_button)
            bot.send_message(
                message.chat.id,
                f"Вы точно хотите забанить пользователя: {name} (@{username})?",
                reply_markup=markup
            )
        else:
            bot.send_message(message.chat.id, "Пользователь с таким ID не найден.")
    except ValueError:
        bot.send_message(message.chat.id, "Введите корректный ID пользователя.")

def ask_ban_reason(message, user_id, duration):
    msg = bot.send_message(message.chat.id, "Укажите причину бана.")
    bot.register_next_step_handler(msg, save_ban, user_id, duration)

# Обработка выбора длительности бана
@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_ban_"))
def confirm_ban(call):
    user_id = int(call.data.split("_")[-1])
    msg = bot.send_message(call.message.chat.id, "Укажите длительность бана (например, '30 секунд', '7 минут', '1 день').")
    bot.register_next_step_handler(msg, set_ban_duration, user_id)
    bot.delete_message(call.message.chat.id, call.message.message_id)

# Установка длительности бана и запрос причины
def set_ban_duration(message, user_id):
    try:
        duration = parse_duration(message.text)
        if not duration:
            raise ValueError("Неверный формат длительности")
        ask_ban_reason(message, user_id, duration)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат длительности. Попробуйте еще раз. Укажите, например: '7 дней', '30 минут', '1 час'.")

# Установка длительности бана
def save_ban(message, user_id, duration):
    reason = message.text
    admin_name = message.from_user.username
    ban_end_time = datetime.now() + duration
    cursor.execute(
        "INSERT OR REPLACE INTO banned_users (user_id, ban_end_time, ban_reason) VALUES (?, ?, ?)", 
        (user_id, ban_end_time, reason)
    )
    conn.commit()
    
    bot.send_message(
        user_id, 
        f"👮 Ты был забанен администратором!\n\n"
        f"Причина: {reason}\nСрок: {duration}\n"
        f"Тебя забанил: @{admin_name}\n\n"
        f"Считаешь бан несправедливым? Напиши об этом @akmdnepr", 
        reply_markup=types.ReplyKeyboardRemove()
    )
    bot.send_message(message.chat.id, "✅ Пользователь был успешно забанен.")

# Преобразование введенного времени в timedelta
def parse_duration(duration_str):
    # Регулярное выражение для поиска числа и единицы времени
    match = re.match(r"(\d+)\s*(\w+)", duration_str, re.IGNORECASE)
    if not match:
        return None
    
    amount = int(match.group(1))
    unit = match.group(2).lower()

    # Словарь для преобразования единиц измерения с поддержкой разных форм
    units = {
        'секунда': ['секунда', 'секунды', 'секунд'],
        'минута': ['минута', 'минуты', 'минут'],
        'час': ['час', 'часа', 'часов'],
        'день': ['день', 'дня', 'дней']
    }

    # Функция для поиска подходящего ключа по словарю units
    def get_unit_key(unit):
        for key, forms in units.items():
            if unit in forms:
                return key
        return None

    # Определение единицы измерения и преобразование в timedelta
    key = get_unit_key(unit)
    if key == 'секунда':
        return timedelta(seconds=amount)
    elif key == 'минута':
        return timedelta(minutes=amount)
    elif key == 'час':
        return timedelta(hours=amount)
    elif key == 'день':
        return timedelta(days=amount)
    else:
        return None

def is_user_banned(user_id):
    cursor.execute("SELECT ban_end_time FROM banned_users WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    if result:
        ban_end_time = datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S.%f')
        if datetime.now() < ban_end_time:
            return True
    return False


@bot.message_handler(func=lambda message: is_user_banned(message.from_user.id))
def delete_message_if_banned(message):
    bot.delete_message(message.chat.id, message.message_id)

def check_ban_expiration():
    cursor.execute("SELECT user_id, ban_end_time FROM banned_users")
    banned_users = cursor.fetchall()
    for user_id, ban_end_time_str in banned_users:
        ban_end_time = datetime.strptime(ban_end_time_str, '%Y-%m-%d %H:%M:%S.%f')
        if datetime.now() >= ban_end_time:
            cursor.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            conn.commit()
            text = f"👮Срок твоего бана истек! Теперь у тебя есть доступ ко всему функционалу бота\nЕсли забыл какие-либо команды напиши /help"
            show_schedule_buttons(user_id, text)

# Обработка отмены бана
@bot.callback_query_handler(func=lambda call: call.data == "cancel_ban")
def cancel_ban(call):
    bot.send_message(call.message.chat.id, "Бан отменен.")
    bot.delete_message(call.message.chat.id, call.message.message_id)

        
def get_help_message(user_id):
    help_message = "👤 Команды для пользователя:\n"
    for command in commands:
        help_message += f"/{command.command} - {command.description}\n"
    
    if user_id in admin_ids:
        help_message += "\n🔒 Команды для администраторов:\n"
        for command in admin_commands:
            help_message += f"/{command.command} - {command.description}\n"
    
    if user_id == god_id:
        help_message += "\n👑 Команды для владельца:\n"
        for command in god_commands:
            help_message += f"/{command.command} - {command.description}\n"

    return help_message

schedule_sent_today = config.get('schedule_sent_today')
user_data = {}
start_time = time.time()

def is_admin(user_id):
    return user_id in admin_ids

@bot.message_handler(commands=['clear_chat'])
def clear_chat(message):
    bot.send_message(message.chat.id, "Команда больше не доступна")

@bot.message_handler(commands=['list_users'])
def list_users(message):
    if message.from_user.id in admin_ids:
        cursor.execute("SELECT user_id, name, birthday, username FROM users")
        users = cursor.fetchall()

        if users:
            response = "Список пользователей:\n\n"
            for user in users:
                user_id, name, birthday, username = user
                response += f"ID: {user_id}\n"
                response += f"Имя: {name}\n"
                response += f"Дата рождения: {birthday}\n"
                response += f"Username: @{username if username else 'не указан'}\n"
                response += "-" * 20 + "\n"
        else:
            response = "В базе данных нет пользователей."

        bot.send_message(message.chat.id, response)
    else:
        bot.send_message(message.chat.id, "У тебя нет прав для использования этой команды.")

@bot.message_handler(commands=['clear_db'])
def clear_database(message):
    if message.from_user.id == god_id:
        msg = bot.send_message(message.chat.id, "Пожалуйста, введите код подтверждения для очистки базы данных.")
        bot.register_next_step_handler(msg, process_confirmation_code)
    else:
        bot.send_message(message.chat.id, "У тебя нет прав для использования этой команды.")

def process_confirmation_code(message):
    if message.text == confirmation_code:
        try:
            cursor.execute('DELETE FROM users')
            cursor.execute('DELETE FROM schedule')
            cursor.execute('DELETE FROM homework')
            cursor.execute('DELETE FROM important_events')
            conn.commit()
            bot.send_message(message.chat.id, "Все таблицы успешно очищены.")
        except Exception as e:
            bot.send_message(message.chat.id, f"Произошла ошибка при очистке базы данных: {e}")
    else:
        bot.send_message(message.chat.id, "Неверный код подтверждения. Очистка базы данных отменена.")


def show_schedule_buttons(chatid, text):
    markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True)
    itembtn1 = types.KeyboardButton('Понедельник')
    itembtn2 = types.KeyboardButton('Вторник')
    itembtn3 = types.KeyboardButton('Среда')
    itembtn4 = types.KeyboardButton('Четверг')
    itembtn5 = types.KeyboardButton('Пятница')
    markup.add(itembtn1, itembtn2, itembtn3, itembtn4, itembtn5)
    
    bot.send_message(chatid, text, reply_markup=markup)

def add_schedule_day(day, message):
    if message.from_user.id not in admin_ids:
        bot.send_message(message.chat.id, "У тебя нет прав для выполнения этой команды.")
        return
    
    cursor.execute('DELETE FROM schedule WHERE day_of_week = ?', (day,))
    conn.commit()

    bot.send_message(message.chat.id, f"Ты заполняешь расписание на {day}. Введи название предмета или напиши 'стоп' для завершения.")
    bot.register_next_step_handler(message, lambda msg: ask_lesson_info(day, 1, msg))

confirmation_code = config['code']

def ask_lesson_info(day, lesson_number, message):
    if message.text.lower() == 'стоп':
        bot.send_message(message.chat.id, f"Заполнение расписания на {day} завершено.")
        return
    
    subject = message.text
    
    cursor.execute('SELECT subject FROM homework WHERE subject=?', (subject,))
    existing_subject = cursor.fetchone()

    if not existing_subject:
        cursor.execute('INSERT INTO homework (subject, homework) VALUES (?, ?)', (subject, 'Домашнее задание еще не задано'))
        conn.commit()
    
    bot.send_message(message.chat.id, f"Введи время начала урока {lesson_number} (в формате ЧЧ:ММ):")
    bot.register_next_step_handler(message, lambda msg: ask_start_time(day, lesson_number, subject, msg))

def ask_start_time(day, lesson_number, subject, message):
    start_time = message.text
    bot.send_message(message.chat.id, f"Введи время окончания урока {lesson_number} (в формате ЧЧ:ММ):")
    bot.register_next_step_handler(message, lambda msg: ask_end_time(day, lesson_number, subject, start_time, msg))

def ask_end_time(day, lesson_number, subject, start_time, message):
    end_time = message.text

    command = generate_command(subject)
    cursor.execute('''
        INSERT INTO schedule (day_of_week, lesson_number, subject, start_time, end_time, command)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (day, lesson_number, subject, start_time, end_time, command))
    conn.commit()

    bot.send_message(message.chat.id, f"Урок {lesson_number} ({subject}) добавлен в расписание на {day}.")
    bot.send_message(message.chat.id, "Введи следующий предмет или напиши 'стоп' для завершения.")
    bot.register_next_step_handler(message, lambda msg: ask_lesson_info(day, lesson_number + 1, msg))

@bot.message_handler(commands=['monday'])
def handle_monday(message):
    add_schedule_day('Monday', message)

@bot.message_handler(commands=['tuesday'])
def handle_tuesday(message):
    add_schedule_day('Tuesday', message)

@bot.message_handler(commands=['wednesday'])
def handle_wednesday(message):
    add_schedule_day('Wednesday', message)

@bot.message_handler(commands=['thursday'])
def handle_thursday(message):
    add_schedule_day('Thursday', message)

@bot.message_handler(commands=['friday'])
def handle_friday(message):
    add_schedule_day('Friday', message)

def ask_name(message):
    user_name = message.text
    user_id = message.from_user.id

    if re.match(r'^[^a-zA-Zа-яА-Я]', user_name):  
        bot.send_message(user_id, "Имя не должно начинаться с специальных символов или цифр. Пожалуйста, введи корректное имя:")
        bot.register_next_step_handler(message, ask_name)
        return

    cursor.execute('INSERT INTO users (user_id, name) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET name=?', (user_id, user_name, user_name))
    conn.commit()
    
    bot.send_message(user_id, f"Приятно познакомиться, {user_name} 😉")
    bot.send_message(user_id, "Теперь скажи, когда у тебя день рождения? (в формате ДД.ММ.ГГГГ)")
    bot.register_next_step_handler_by_chat_id(user_id, ask_birthday)

def ask_birthday(message):
    user_birthday = message.text
    user_id = message.from_user.id
    
    date_pattern = r"^\d{2}\.\d{2}\.\d{4}$"

    if re.match(date_pattern, user_birthday):
        try:
            day, month, year = map(int, user_birthday.split('.'))
            date_valid = datetime(year, month, day)

            cursor.execute('UPDATE users SET birthday=? WHERE user_id=?', (user_birthday, user_id))
            conn.commit()

            show_schedule_buttons(user_id, "Отлично, запомнил!")
            bot.send_message(user_id, "На этом все, если захочешь изменить свои данные используй команду /register")
            bot.send_message(user_id, "Все доступные команды можешь посмотреть по команде /help")

        
        except ValueError:
            bot.send_message(user_id, "Некорректная дата. Пожалуйста, укажи правильную дату рождения в формате ДД.ММ.ГГГГ:")
            bot.register_next_step_handler(message, ask_birthday)
    
    else:
        bot.send_message(user_id, "Некорректный формат. Пожалуйста, укажи дату рождения в формате ДД.ММ.ГГГГ:")
        bot.register_next_step_handler(message, ask_birthday)

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    username = message.from_user.username
    
    cursor.execute('SELECT name, birthday FROM users WHERE user_id=?', (user_id,))
    user = cursor.fetchone()

    if user_id == god_id:
        full_commands = commands + admin_commands + god_commands
    elif is_admin(user_id):
        full_commands = commands + admin_commands
    else:
        full_commands = commands
    
    bot.set_my_commands(full_commands, scope=types.BotCommandScopeChat(message.chat.id))
    
    if user:
        name, birthday = user
        
        if not name:
            show_schedule_buttons(user_id, "Для начала, как мне тебя называть?")
            bot.register_next_step_handler(message, ask_name)
        elif not birthday:
            bot.send_message(user_id, f"Привет, {name}! Я еще не знаю, когда у тебя день рождения.")
            bot.send_message(user_id, "Пожалуйста, укажи дату рождения в формате ДД.ММ.ГГГГ:")
            bot.register_next_step_handler_by_chat_id(user_id, ask_birthday)
        else:
            bot.send_message(user_id, f"С возвращением, {name}! Рад снова тебя видеть! 😊")
            show_schedule_buttons(user_id, "Чем могу быть полезен?")
    else:
        bot.send_message(user_id, "Привет! Я EduMate!👋")
        bot.send_message(user_id, "Что-то я тебя не припоминаю 🤔")
        bot.send_message(user_id, "Не беда, сейчас исправим")
        bot.send_message(user_id, "Для начала, как мне тебя называть?")
        bot.register_next_step_handler(message, ask_name)

    cursor.execute('INSERT INTO users (user_id, username) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET username=?', (user_id, username, username))
    conn.commit()

@bot.message_handler(commands=['get_info'])
def get_user_info(message):
    user_id = message.from_user.id
    
    cursor.execute('SELECT name, birthday, username FROM users WHERE user_id=?', (user_id,))
    user = cursor.fetchone()
    
    if user:
        name, birthday, username = user
        response = f"Вот информация о тебе:\nИмя: {name or 'не указано'}\nДень рождения: {birthday or 'не указан'}\nНикнейм: @{username or 'не указан'}"
    else:
        response = "Я не нашел твоих данных. Попробуй зарегистрироваться снова с помощью команды /start."

    bot.send_message(user_id, response)

@bot.message_handler(commands=['register'])
def reregister(message):
    bot.send_message(message.chat.id, "Давай обновим твою информацию.")
    bot.send_message(message.chat.id, "Как мне тебя называть?")
    bot.register_next_step_handler(message, ask_name)


def add_important_event(start_date, end_date, event_text):
    cursor.execute('''
    INSERT INTO important_events (start_date, end_date, event_text)
    VALUES (?, ?, ?)
    ''', (start_date, end_date, event_text))
    conn.commit()

def delete_important_event(event_id):
    cursor.execute('''
    DELETE FROM important_events WHERE id=?
    ''', (event_id,))
    conn.commit()

user_messages = {}

def get_important_events():
    now = datetime.now(timezone).strftime('%Y-%m-%d')
    cursor.execute('SELECT * FROM important_events WHERE end_date >= ?', (now,))
    events = cursor.fetchall()
    return events

def remove_expired_events():
    now = datetime.now(timezone).strftime('%Y-%m-%d')
    cursor.execute('DELETE FROM important_events WHERE end_date < ?', (now,))
    conn.commit()

def send_important_events(user_id, schedule_message_id):
    events = get_important_events()
    
    if user_id not in user_messages:
        user_messages[user_id] = []
    
    if not events:
        attach_collapse_button(user_id, schedule_message_id, 'schedule')
        return
    
    response = "📢 <b>Важные события:</b>\n\n"
    for event in events:
        response += f"🔹 {event[3]}\n"
    
    event_message = bot.send_message(user_id, response, parse_mode="HTML")
    
    user_messages[user_id].append(event_message.message_id)
    
    attach_collapse_button(user_id, event_message.message_id, 'schedule')

def attach_collapse_button(user_id, message_id, message_type='schedule'):
    markup = InlineKeyboardMarkup()
    
    collapse_button = InlineKeyboardButton(
        text="Свернуть", 
        callback_data=f'{message_type}_collapse_{user_id}_{message_id}'
    )
    
    markup.add(collapse_button)
    
    bot.edit_message_reply_markup(user_id, message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('schedule_collapse_'))
def handle_schedule_collapse(call):
    user_id, message_id = map(int, call.data.split('_')[2:])
    
    if user_id in user_messages:
        for msg_id in user_messages[user_id]:
            try:
                bot.delete_message(call.message.chat.id, msg_id)
            except Exception as e:
                pass

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            pass

        del user_messages[user_id]

@bot.message_handler(commands=['help'])
def send_help(message: Message):
    user_id = message.from_user.id
    help_message = get_help_message(user_id)
    bot.send_message(message.chat.id, help_message)

schedule.every().day.at("00:05").do(remove_expired_events)

@bot.message_handler(func=lambda message: message.text in ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'])
def show_day_schedule(message):
    user_id = message.from_user.id
    days_translation = {
        'Понедельник': 'Monday',
        'Вторник': 'Tuesday',
        'Среда': 'Wednesday',
        'Четверг': 'Thursday',
        'Пятница': 'Friday'
    }
    
    day = days_translation[message.text]
    
    if user_id not in user_messages:
        user_messages[user_id] = []
    
    user_messages[user_id].append(message.message_id)
    
    cursor.execute('SELECT lesson_number, subject, start_time, end_time, command FROM schedule WHERE day_of_week=? ORDER BY lesson_number', (day,))
    lessons = cursor.fetchall()
    
    if lessons:
        response = f"📅 <b>Расписание на {message.text}:</b>\n\n"
        for lesson_number, subject, start_time, end_time, command in lessons:
            response += f"🔹 <b>{lesson_number}</b>. <b>{subject}</b> {start_time} - {end_time}\n"
            response += f"   🔸 <i>Домашнее задание:</i> \n   {command}\n\n"
        
        schedule_message = bot.send_message(message.chat.id, response, parse_mode="HTML")
        user_messages[user_id].append(schedule_message.message_id)
        send_important_events(user_id, schedule_message.message_id)
    else:
        empty_schedule_message = bot.send_message(message.chat.id, f"🔹 На {message.text} пока нет расписания")
        user_messages[user_id].append(empty_schedule_message.message_id)
        send_important_events(user_id, empty_schedule_message.message_id)

tips = [
    "Пропали кнопки? Напиши /start",
    "Есть какие-то предложения по боту? Напиши /message_admin",
    "Домашка на какой-то предмет неактуальна? Напиши /homework и обнови!",
    "Бот перестал работать? Напиши об этом @akmdnepr",
    "Есть вопросы? Напиши /message_admin"
]

def load_config():
    with open('config.json', 'r') as file:
        return json.load(file)

def save_config(config):
    with open('config.json', 'w') as file:
        json.dump(config, file)

def check_schedule():
    now = datetime.now(timezone)
    current_time = now.strftime("%H:%M")
    current_day = now.strftime("%A")

    local_cursor = conn.cursor()

    local_cursor.execute('SELECT id, lesson_number, start_time, end_time, subject, reminded FROM schedule WHERE day_of_week=?', (current_day,))
    lessons = local_cursor.fetchall()

    config = load_config()
    today_date = now.strftime("%Y-%m-%d")
    tips_sent = config.get('date') == today_date and config.get('tips_sent', False)

    for lesson_id, lesson_number, start_time, end_time, subject, reminded in lessons:
        if subject == "Ничего":
            local_cursor.execute('UPDATE schedule SET reminded=3 WHERE id=?', (lesson_id,))
            conn.commit()
            continue 
        lesson_time = datetime.strptime(start_time, "%H:%M").replace(tzinfo=timezone)
        end_time_dt = datetime.strptime(end_time, "%H:%M").replace(tzinfo=timezone)

        lesson_time = now.replace(hour=lesson_time.hour, minute=lesson_time.minute, second=0, microsecond=0)
        end_time_dt = now.replace(hour=end_time_dt.hour, minute=end_time_dt.minute, second=0, microsecond=0)

        if 0 <= (lesson_time - now).total_seconds() <= 300 and reminded == 0:
            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    text = f"🟠Скоро начнется {subject}! Время начала {start_time}."
                    show_schedule_buttons(user_id, text)
                except TelegramError:
                    pass

            local_cursor.execute('UPDATE schedule SET reminded=1 WHERE id=?', (lesson_id,))
            conn.commit()

        if now >= lesson_time and now <= lesson_time + timedelta(minutes=1) and reminded == 1:
            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    bot.send_message(user_id, f"🔴Урок {subject} начался!")
                except TelegramError:
                    pass

            local_cursor.execute('UPDATE schedule SET reminded=2 WHERE id=?', (lesson_id,))
            conn.commit()

        if now >= end_time_dt and reminded == 2:
            local_cursor.execute('SELECT lesson_number, start_time, subject FROM schedule WHERE day_of_week=? AND lesson_number=?', (current_day, lesson_number + 1))
            next_lesson = local_cursor.fetchone()

            if next_lesson:
                next_lesson_number, next_start_time, next_subject = next_lesson
                next_start_time_dt = datetime.strptime(next_start_time, "%H:%M").replace(tzinfo=timezone)

                if next_start_time_dt < end_time_dt:
                    next_start_time_dt += timedelta(days=1)

                break_duration = int((next_start_time_dt - end_time_dt).total_seconds() // 60)

                message = f"🟢Урок №{lesson_number} закончился! Следующий урок ({next_subject}) начнется в {next_start_time}."
            else:
                message = f"🟢Урок №{lesson_number} закончился! Это был последний урок на сегодня."


            local_cursor.execute('SELECT user_id FROM users')
            users = local_cursor.fetchall()

            for user_id, in users:
                try:
                    bot.send_message(user_id, message)
                except TelegramError:
                    pass

            if lesson_number == 2 and not tips_sent:
                random.shuffle(tips) 
                random.shuffle(users)

                for user, tip in zip(users, tips):
                    user_id = user[0]
                    try:
                        bot.send_message(user_id, f"💡 Случайная подсказка:\n{tip}")
                    except TelegramError:
                        pass

                config['date'] = today_date
                config['tips_sent'] = True
                save_config(config)

            local_cursor.execute('UPDATE schedule SET reminded=0 WHERE id=?', (lesson_id,))
            conn.commit()
    check_ban_expiration()
schedule.every().second.do(check_schedule)

admin_id = god_id

def relative_date(date_str):
    from datetime import datetime, date as dt

    if not date_str:
        return ""

    try:
        if isinstance(date_str, str):
            date = datetime.strptime(date_str, '%Y-%m-%d').date()
        else:
            date = date_str

    except ValueError:
        return "Неверный формат даты"

    today = dt.today()
    delta = today - date

    if delta.days == 0:
        return "Сегодня"
    elif delta.days == 1:
        return "Вчера"
    else:
        days = delta.days
        if 11 <= days % 100 <= 19:  
            day_word = "дней"
        else:
            last_digit = days % 10
            if last_digit == 1:
                day_word = "день"
            elif 2 <= last_digit <= 4:
                day_word = "дня"
            else:
                day_word = "дней"
        return f"{days} {day_word} назад"
    
def save_message_to_db(chat_id, user_id, message_id, has_buttons=0):
    cursor.execute('''
        INSERT INTO messages (chat_id, user_id, message_id, has_buttons) 
        VALUES (?, ?, ?, ?)
    ''', (chat_id, user_id, message_id, has_buttons))
    conn.commit()

def delete_messages_from_db(chat_id, user_id):
    cursor.execute('SELECT message_id FROM messages WHERE chat_id=? AND user_id=?', (chat_id, user_id))
    messages = cursor.fetchall()
    
    for message_id in messages:
        try:
            bot.delete_message(chat_id, message_id[0])
        except Exception as e:
            print(f"Ошибка при удалении сообщения {message_id[0]}: {e}")

    cursor.execute('DELETE FROM messages WHERE chat_id=? AND user_id=?', (chat_id, user_id))
    conn.commit()

@bot.message_handler(commands=['homework'])
def handle_homework(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    msg = bot.send_message(chat_id, "Введи название урока, на который хочешь записать дз:")
    save_message_to_db(chat_id, user_id, msg.message_id)
    update_homework_state(user_id, chat_id, None, None, None, 'get_homework')
    bot.register_next_step_handler(msg, get_homework)

def get_homework(message):
    subject = message.text
    chat_id = message.chat.id
    user_id = message.from_user.id

    save_message_to_db(chat_id, user_id, message.message_id)

    update_homework_state(user_id, chat_id, subject, None, None, 'collect_homework_data')

    cursor.execute('SELECT homework, photo_ids, date FROM homework WHERE LOWER(subject)=LOWER(?)', (subject,))
    lesson = cursor.fetchone()

    if lesson:
        homework_text, photo_ids, date = lesson
        if date:
            date = datetime.strptime(date, '%Y-%m-%d').date()
            date_text = f"\n🔸Дата последнего изменения: {relative_date(date)}"
        else:
            date_text = f"\n🔸Дата последнего изменения не указана."

        current_homework_message = f"\n🔸Текущее задание для {subject}:\n\n{homework_text}\n{date_text}"

        media = []
        if photo_ids:
            photos = photo_ids.split(',')
            for i, photo in enumerate(photos):
                if i == len(photos) - 1:
                    media.append(types.InputMediaPhoto(photo, caption=current_homework_message))
                else:
                    media.append(types.InputMediaPhoto(photo))

            sent_messages = bot.send_media_group(chat_id, media)
            for msg in sent_messages:
                save_message_to_db(chat_id, user_id, msg.message_id)
        else:
            msg = bot.send_message(chat_id, current_homework_message)
            save_message_to_db(chat_id, user_id, msg.message_id)

        markup = types.InlineKeyboardMarkup()
        yes_button = types.InlineKeyboardButton("Да", callback_data=f'overwrite_yes|{subject}')
        no_button = types.InlineKeyboardButton("Нет", callback_data='overwrite_no')
        markup.add(yes_button, no_button)

        msg = bot.send_message(chat_id, "Точно хочешь заменить это задание?", reply_markup=markup)
        save_message_to_db(chat_id, user_id, msg.message_id, has_buttons=1)

        # Чекпоинт: записываем шаг `awaiting_confirmation` в базу
        update_homework_state(user_id, chat_id, subject, None, None, 'awaiting_confirmation')
    else:
        bot.send_message(chat_id, "Урок с таким названием не найден.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('overwrite_yes') or call.data == 'overwrite_no')
def confirm_overwrite(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    delete_messages_from_db(chat_id, user_id)

    if call.data == 'overwrite_no':
        bot.send_message(chat_id, "Операция отменена. Напиши /homework, если хочешь попробовать снова")
    else:
        subject = call.data.split('|')[1]
        msg = bot.send_message(chat_id, f"Введи новое текстовое задание для {subject}:")
        save_message_to_db(chat_id, user_id, msg.message_id)
        
        bot.register_next_step_handler(msg, lambda msg: collect_homework_data(subject, msg))


def collect_homework_data(subject, message):
    homework = message.text
    chat_id = message.chat.id
    user_id = message.from_user.id

    save_message_to_db(chat_id, user_id, message.message_id)

    update_homework_state(user_id, chat_id, subject, homework, None, 'collect_photos')

    msg = bot.send_message(message.chat.id, "Если нужно - прикрепи фото. Если фото нет, напиши 'стоп'")
    save_message_to_db(chat_id, user_id, msg.message_id)

    bot.register_next_step_handler(msg, lambda msg: collect_photos(subject, homework, [], msg))


def collect_photos(subject, homework, photo_ids, message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    save_message_to_db(chat_id, user_id, message.message_id)

    if message.text and message.text.lower() == 'стоп':
        save_homework_to_db(subject, homework, photo_ids, user_id, message.from_user.username)
        delete_messages_from_db(chat_id, user_id)

        cursor.execute('DELETE FROM homework_state WHERE user_id=?', (user_id,))
        conn.commit()

        bot.send_message(message.chat.id, f"Домашнее задание отправлено. Спасибо за помощь ☺️\n\nНапиши /homework, если хочешь заполнить другие задания")
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        photo_ids.append(file_id)
        
        update_homework_state(user_id, chat_id, subject, homework, ','.join(photo_ids), 'collect_photos')

        msg = bot.send_message(message.chat.id, "Фото получено. Отправь ещё одно или напиши 'стоп' для завершения.")
        save_message_to_db(chat_id, user_id, msg.message_id)

    bot.register_next_step_handler(message, lambda msg: collect_photos(subject, homework, photo_ids, msg))

def save_homework_to_db(subject, homework_text, photo_ids, chat_id, username):
    photo_ids_str = ','.join(photo_ids) if photo_ids else None
    today = date.today().strftime('%Y-%m-%d')

    cursor.execute('UPDATE homework SET homework=?, photo_ids=?, date=? WHERE subject=?',
                   (homework_text, photo_ids_str, today, subject))
    conn.commit()

    notify_admin(subject, homework_text, photo_ids, chat_id, username)
    

def notify_admin(subject, homework_text, photo_ids, chat_id, username):
    homework_message = (f"❗️Новое домашнее задание❗️\n\n"
                        f"▫️Отправитель: @{username} (ID: {chat_id})\n\n"
                        f"▫️Предмет: {subject}\n\n"
                        f"▫️Текст задания:\n\n{homework_text}")

    if photo_ids:
        media_group = []
        
        for index, file_id in enumerate(photo_ids):
            if index == 0:
                media_group.append(types.InputMediaPhoto(file_id, caption=homework_message))
            else:
                media_group.append(types.InputMediaPhoto(file_id))
        
        bot.send_media_group(god_id, media_group)
    else:
        bot.send_message(god_id, homework_message)

def update_homework_state(user_id, chat_id, subject, homework, photo_ids, step):
    cursor.execute('''
        INSERT INTO homework_state (user_id, chat_id, subject, homework, photo_ids, step)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
        chat_id=excluded.chat_id,
        subject=excluded.subject,
        homework=excluded.homework,
        photo_ids=excluded.photo_ids,
        step=excluded.step
    ''', (user_id, chat_id, subject, homework, photo_ids, step))
    conn.commit()


def check_unfinished_states():
    # Проверяем все незавершенные состояния в базе данных
    cursor.execute('SELECT user_id, chat_id, subject, homework, photo_ids, step FROM homework_state')
    unfinished_states = cursor.fetchall()

    for user_id, chat_id, subject, homework, photo_ids, step in unfinished_states:
        bot.send_message(chat_id, "Извиняюсь, я перезапустился. Продолжаем с того же места.")
        
        # В зависимости от текущего шага, продолжаем выполнение
        if step == 'get_homework':
            if not subject:  # Если предмет не задан, просим ввести его
                bot.send_message(chat_id, "Пожалуйста, введи название урока.")
                bot.register_next_step_handler_by_chat_id(chat_id, get_homework)
            else:
                # Если предмет уже введен, предложим подтвердить замену
                send_confirmation_request(chat_id, subject)
        elif step == 'awaiting_confirmation':
            # Если бот ждал подтверждения, не отправляем сообщение повторно, просто уведомляем пользователя
            bot.send_message(chat_id, "Жду подтверждения на замену задания.")
        elif step == 'collect_homework_data':
            if not homework:
                bot.send_message(chat_id, f"Введи новое текстовое задание для {subject}.")
                bot.register_next_step_handler_by_chat_id(chat_id, lambda msg: collect_homework_data(subject, msg))
            else:
                collect_photos(subject, homework, photo_ids)
        elif step == 'collect_photos':
            bot.send_message(chat_id, "Если нужно, прикрепи фото. Если фото нет, напиши 'стоп'.")
            bot.register_next_step_handler_by_chat_id(chat_id, lambda msg: collect_photos(subject, homework, photo_ids.split(','), msg))


def send_confirmation_request(chat_id, subject):
    # Отправляем сообщение с кнопками подтверждения
    markup = types.InlineKeyboardMarkup()
    yes_button = types.InlineKeyboardButton("Да", callback_data=f'overwrite_yes|{subject}')
    no_button = types.InlineKeyboardButton("Нет", callback_data='overwrite_no')
    markup.add(yes_button, no_button)

    msg = bot.send_message(chat_id, "Точно хочешь заменить это задание?", reply_markup=markup)
    # Обновляем состояние пользователя, чтобы отметить, что мы ждем подтверждения
    cursor.execute('UPDATE homework_state SET step=? WHERE chat_id=?', ('awaiting_confirmation', chat_id))
    conn.commit()
    # Регистрируем обработчик для обработки ответа на подтверждение
    bot.register_callback_query_handler(handle_confirmation_response, lambda call: call.data.startswith('overwrite_yes') or call.data == 'overwrite_no')

def handle_confirmation_response(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    if call.data == 'overwrite_no':
        bot.send_message(chat_id, "Операция отменена. Напиши /homework, если хочешь попробовать снова.")
        cursor.execute('DELETE FROM homework_state WHERE user_id=?', (user_id,))
        conn.commit()
    else:
        subject = call.data.split('|')[1]
        msg = bot.send_message(chat_id, f"Введи новое текстовое задание для {subject}.")
        save_message_to_db(chat_id, user_id, msg.message_id)
        update_homework_state(user_id, chat_id, subject, None, None, 'collect_homework_data')
        bot.register_next_step_handler(msg, lambda msg: collect_homework_data(subject, msg))

@bot.message_handler(commands=['delete_homework'])
def handle_delete_homework(message):
    if message.from_user.id == admin_id:
        bot.send_message(message.chat.id, "Укажи ID домашнего задания для удаления:")
        bot.register_next_step_handler(message, delete_homework)
    else:
        bot.send_message(message.chat.id, "У тебя нет прав для выполнения этой команды.")

def delete_homework(message):
    try:
        homework_id = int(message.text)

        cursor.execute('SELECT * FROM homework WHERE id=?', (homework_id,))
        homework_data = cursor.fetchone()

        if homework_data:
            cursor.execute('DELETE FROM homework WHERE id=?', (homework_id,))
            conn.commit()

            bot.send_message(message.chat.id, f"Домашнее задание с ID {homework_id} успешно удалено.")
        else:
            bot.send_message(message.chat.id, "Запись с таким ID не найдена.")
    
    except ValueError:
        bot.send_message(message.chat.id, "Некорректный формат ID. Введите числовое значение.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка: {e}")
        
def reset_reminders():
    backup_folder = 'beneki_backup'
    
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)
    
    for filename in os.listdir(backup_folder):
        file_path = os.path.join(backup_folder, filename)
        if os.path.isfile(file_path):
            os.remove(file_path)
    
    shutil.copy('users.db', backup_folder)
    
    local_cursor = conn.cursor()
    local_cursor.execute('UPDATE schedule SET reminded=0')
    conn.commit()


schedule.every().day.at("00:01").do(reset_reminders)

def check_end_of_day():
    global schedule_sent_today 

    now = datetime.now(timezone)
    current_day = now.strftime("%A")
    current_time = now.strftime("%H:%M")

    days_translation = {
        'Monday': 'Понедельник',
        'Tuesday': 'Вторник',
        'Wednesday': 'Среда',
        'Thursday': 'Четверг',
        'Friday': 'Пятница',
        'Saturday': 'Суббота',
        'Sunday': 'Воскресенье'
    }
    
    if schedule_sent_today:
        return False  

    conn = sqlite3.connect('users.db')  
    cursor = conn.cursor()

    try:
        cursor.execute('SELECT end_time FROM schedule WHERE day_of_week=? ORDER BY lesson_number DESC LIMIT 1', (current_day,))
        last_lesson = cursor.fetchone()

        if last_lesson:
            last_end_time = last_lesson[0]
            if current_time >= last_end_time: 
                next_day_eng = (now + timedelta(days=1)).strftime("%A")
                next_day_rus = days_translation.get(next_day_eng, next_day_eng)  

                cursor.execute('SELECT lesson_number, subject, start_time, end_time, command FROM schedule WHERE day_of_week=? ORDER BY lesson_number', (next_day_eng,))
                lessons_tomorrow = cursor.fetchall()
                
                cursor.execute('SELECT user_id FROM users')
                users = cursor.fetchall()

                for user_id, in users:
                    try:
                        if lessons_tomorrow:
                            response = f"📅 <b>Расписание на завтра ({next_day_rus}):</b>\n\n"
                            for lesson_number, subject, start_time, end_time, command in lessons_tomorrow:
                                response += f"🔹 <b>{lesson_number}</b>. <b>{subject}</b> {start_time} - {end_time}\n"
                                response += f"   🔸 <i>Домашнее задание:</i> \n   {command}\n\n"
                            
                            message = bot.send_message(user_id, response, parse_mode="HTML")
                            send_important_events(user_id, message.message_id) 
                        else:
                            message = bot.send_message(user_id, "🔹 Поздравляю, завтра у тебя нет уроков!")
                            send_important_events(user_id, message.message_id)  
                    
                    except TelegramError:
                        pass

                schedule_sent_today = True
                config['schedule_sent_today'] = True
                save_config(config)
                return True
    finally:
        cursor.close()
        conn.close()

    return False

def reset_schedule_flag():
    global schedule_sent_today
    schedule_sent_today = False
    config['schedule_sent_today'] = False
    save_config(config)

schedule.every().day.at("00:01").do(reset_schedule_flag)

schedule.every().minute.do(check_end_of_day)

def generate_command(subject_name):
    subject_name = subject_name.lower().replace(' ', '_') 
    subject_name = subject_name.replace('/', '_').replace('.', '_')  
    subject_name = transliterate.translit(subject_name, reversed=True)  
    command = f"/h_{subject_name}"
    return command


@bot.message_handler(func=lambda message: message.text.startswith('/h_'))
def handle_homework_command(message):
    command = message.text

    cursor.execute('SELECT subject FROM schedule WHERE command=?', (command,))
    subject_data = cursor.fetchone()

    if subject_data:
        subject = subject_data[0]

        cursor.execute('SELECT homework, photo_ids, date FROM homework WHERE subject=?', (subject,))
        homework_data = cursor.fetchone()

        if homework_data:
            homework, photo_ids, homework_date = homework_data

            if homework_date:
                last_modified_message = f"\n\nПоследнее изменение: {relative_date(homework_date)}"
            else:
                last_modified_message = ""

            full_homework_message = f"{homework}{last_modified_message}"

            if photo_ids:
                photo_ids_list = photo_ids.split(',')
                media_group = []
                for photo_id in photo_ids_list:
                    media_group.append(types.InputMediaPhoto(photo_id, caption=full_homework_message if len(media_group) == 0 else ''))

                media_messages = bot.send_media_group(message.chat.id, media_group)
                media_message_ids = [media.message_id for media in media_messages]

                markup = types.InlineKeyboardMarkup()
                collapse_button = types.InlineKeyboardButton(
                    "Свернуть", 
                    callback_data=f'homework_collapse_{message.message_id}_{",".join(map(str, media_message_ids))}'
                )
                markup.add(collapse_button)

                bot.send_message(message.chat.id, "Нажми чтобы свернуть", reply_markup=markup)
            else:
                markup = types.InlineKeyboardMarkup()
                collapse_button = types.InlineKeyboardButton(
                    "Свернуть", 
                    callback_data=f'homework_collapse_{message.message_id}_{message.message_id}'
                )
                markup.add(collapse_button)

                bot.send_message(message.chat.id, full_homework_message, reply_markup=markup)
        else:
            bot.send_message(message.chat.id, f"Домашнее задание для предмета {subject} не найдено.")
    else:
        bot.send_message(message.chat.id, f"Команда {command} не распознана. Возможно возникла ошибка при генерации команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('homework_collapse_'))
def handle_homework_collapse(call):
    data_parts = call.data.split('_')
    user_message_id = int(data_parts[2])
    message_ids = data_parts[3].split(',')

    try:
        bot.delete_message(call.message.chat.id, user_message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message to delete not found" not in str(e):
            raise

    for message_id in message_ids:
        try:
            bot.delete_message(call.message.chat.id, int(message_id))
        except telebot.apihelper.ApiTelegramException as e:
            if "message to delete not found" not in str(e):
                raise

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except telebot.apihelper.ApiTelegramException as e:
        if "message to delete not found" not in str(e):
            raise

@bot.message_handler(commands=['add_event'])
def start_add_event(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    bot.send_message(message.chat.id, "Введи дату начала уведомлений (в формате ДД.ММ):")
    bot.register_next_step_handler(message, process_start_date)

def process_start_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        start_date_input = message.text.strip()
        start_date = datetime.strptime(start_date_input + f".{datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id] = {'start_date': start_date}
        bot.send_message(message.chat.id, "Введи дату окончания уведомлений (в формате ДД.ММ):")
        bot.register_next_step_handler(message, process_end_date)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_start_date)

def process_start_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        start_date_input = message.text.strip()
        start_date = datetime.strptime(start_date_input + f".{datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id] = {'start_date': start_date}
        bot.send_message(message.chat.id, "Введи дату окончания уведомлений (в формате ДД.ММ):")
        bot.register_next_step_handler(message, process_end_date)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_start_date)

def process_end_date(message):
    if not is_admin(message.from_user.id):
        return

    try:
        end_date_input = message.text.strip()
        end_date = datetime.strptime(end_date_input + f".{datetime.now().year}", "%d.%m.%Y").date()

        user_data[message.from_user.id]['end_date'] = end_date
        bot.send_message(message.chat.id, "Введи текст события:")
        bot.register_next_step_handler(message, process_event_text)
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат даты. Пожалуйста, используй формат ДД.ММ.")
        bot.register_next_step_handler(message, process_end_date)


def process_event_text(message):
    if not is_admin(message.from_user.id):
        return

    try:
        event_text = message.text.strip()
        user_id = message.from_user.id
        
        start_date = user_data[user_id]['start_date']
        end_date = user_data[user_id]['end_date']

        add_important_event(start_date, end_date, event_text)
        
        bot.send_message(message.chat.id, "Событие успешно добавлено.")
        
        del user_data[user_id]
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")
        if user_id in user_data:
            del user_data[user_id]

@bot.message_handler(commands=['delete_event'])
def delete_event_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    try:
        event_id = int(message.text.split(' ')[1])
        delete_important_event(event_id)
        bot.reply_to(message, f"Событие с ID {event_id} удалено.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

@bot.message_handler(commands=['list_events'])
def list_events_command(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "У тебя нет прав для выполнения этой команды.")
        return

    cursor.execute('SELECT id, start_date, end_date, event_text FROM important_events')
    events = cursor.fetchall()

    if events:
        response = "📅 <b>Важные события:</b>\n\n"
        for event in events:
            event_id, start_date, end_date, event_text = event
            response += f"🔹 <b>ID:</b> {event_id}\n   <b>Событие:</b> {event_text}\n   <b>С {start_date} по {end_date}</b>\n\n"
        bot.send_message(message.chat.id, response, parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "Нет запланированных событий.")

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)


scheduler_thread = threading.Thread(target=run_scheduler)
scheduler_thread.start()

days_mapping = {
    'Понедельник': 'Monday',
    'Вторник': 'Tuesday',
    'Среда': 'Wednesday',
    'Четверг': 'Thursday',
    'Пятница': 'Friday'
}

@bot.message_handler(commands=['edit_lesson'])
def edit_lesson(message: Message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"edit_day_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('edit_day_'))
def select_day(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]
    day_of_week_eng = days_mapping[day_of_week_rus]
    bot.send_message(call.message.chat.id, f"Вы выбрали {day_of_week_rus}. Введите номер урока:")
    bot.register_next_step_handler(call.message, process_edit_lesson, day_of_week_eng)

def process_edit_lesson(message: Message, day_of_week):
    try:
        lesson_number = message.text
        bot.send_message(message.chat.id, "Введите предмет, время начала и конца (Пример: Физра 15:30 16:00):")
        bot.register_next_step_handler(message, finalize_edit_lesson, day_of_week, lesson_number)
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

def finalize_edit_lesson(message: Message, day_of_week, lesson_number):
    try:
        data = message.text.rsplit(' ', 2)
        if len(data) == 3:
            subject, start_time, end_time = data[0], data[1], data[2]
            homework_link = generate_command(subject)
            
            cursor.execute('SELECT subject FROM homework WHERE subject=?', (subject,))
            existing_subject = cursor.fetchone()
            if not existing_subject:
                cursor.execute('INSERT INTO homework (subject, homework) VALUES (?, ?)', (subject, 'Домашнее задание еще не задано'))
                conn.commit()
            
            cursor.execute('''
                UPDATE schedule
                SET subject = ?, start_time = ?, end_time = ?, command = ?
                WHERE day_of_week = ? AND lesson_number = ?
            ''', (subject, start_time, end_time, homework_link, day_of_week, lesson_number))
            conn.commit()
            
            bot.send_message(message.chat.id, f"Урок {lesson_number} на {day_of_week} изменён.")
        else:
            bot.send_message(message.chat.id, "Неправильный формат. Попробуйте снова.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

@bot.message_handler(commands=['delete_last_lesson'])
def delete_last_lesson(message: Message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"delete_last_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели для удаления последнего урока:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('delete_last_'))
def process_delete_last_lesson(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]
    day_of_week_eng = days_mapping.get(day_of_week_rus)
    if day_of_week_eng:
        try:
            cursor.execute('''
                SELECT MAX(lesson_number) FROM schedule WHERE day_of_week = ?
            ''', (day_of_week_eng,))
            last_lesson_number = cursor.fetchone()[0]
            if last_lesson_number:
                cursor.execute('''
                    DELETE FROM schedule WHERE day_of_week = ? AND lesson_number = ?
                ''', (day_of_week_eng, last_lesson_number))
                conn.commit()
                bot.send_message(call.message.chat.id, f"Последний урок номер {last_lesson_number} на {day_of_week_rus} удалён.")
            else:
                bot.send_message(call.message.chat.id, "Нет уроков на этот день.")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"Ошибка: {str(e)}")
    else:
        bot.send_message(call.message.chat.id, "Неправильный день недели.")



@bot.message_handler(commands=['add_lesson'])
def add_lesson(message: Message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']
        for day in days:
            markup.add(types.InlineKeyboardButton(day, callback_data=f"add_lesson_{day}"))
        bot.send_message(message.chat.id, "Выберите день недели для добавления нового урока:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для использования этой команды.")

@bot.callback_query_handler(func=lambda call: call.data.startswith('add_lesson_'))
def process_add_lesson(call: types.CallbackQuery):
    day_of_week_rus = call.data.split('_')[2]
    day_of_week_eng = days_mapping.get(day_of_week_rus)
    if day_of_week_eng:
        bot.send_message(call.message.chat.id, "Введи предмет, время начала и конца (Пример: Физра 15:30 16:00):")
        bot.register_next_step_handler(call.message, finalize_add_lesson, day_of_week_eng)
    else:
        bot.send_message(call.message.chat.id, "Неправильный день недели.")

def finalize_add_lesson(message: Message, day_of_week):
    try:
        data = message.text.rsplit(' ', 2)
        if len(data) == 3:
            subject, start_time, end_time = data[0], data[1], data[2]
            command = generate_command(subject)
            
            cursor.execute('SELECT subject FROM homework WHERE subject=?', (subject,))
            existing_subject = cursor.fetchone()
            if not existing_subject:
                cursor.execute('INSERT INTO homework (subject, homework) VALUES (?, ?)', (subject, 'Домашнее задание еще не задано'))
                conn.commit()
            
            cursor.execute('SELECT MAX(lesson_number) FROM schedule WHERE day_of_week = ?', (day_of_week,))
            last_lesson_number = cursor.fetchone()[0] or 0
            new_lesson_number = last_lesson_number + 1
            
            cursor.execute('''
                INSERT INTO schedule (day_of_week, lesson_number, subject, start_time, end_time, command)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (day_of_week, new_lesson_number, subject, start_time, end_time, command))
            conn.commit()
            
            bot.send_message(message.chat.id, f"Новый урок добавлен в {day_of_week}: {subject} ({start_time} - {end_time})")
        else:
            bot.send_message(message.chat.id, "Неправильный формат. Попробуйте снова.")
    except Exception as e:
        bot.send_message(message.chat.id, f"Ошибка: {str(e)}")

def check_birthdays():
    today = datetime.today().strftime('%d.%m')

    cursor.execute("SELECT user_id, name, birthday FROM users")
    users = cursor.fetchall()

    for user in users:
        user_id = user[0]
        name = user[1]
        birthday = user[2]

        if birthday and isinstance(birthday, str) and len(birthday) >= 5:
            birthday_day_month = birthday[:5]
            
            if birthday_day_month == today:
                send_birthday_message(user_id, name)
        else:
            print(f"Проблема с датой рождения для пользователя {name} (ID: {user_id}).")

def send_birthday_message(user_id, name):
    message = f"🎉{name}, поздравляю с Днём Рождения! 🎂🥳 Желаю всего наилучшего!"
    bot.send_message(user_id, message)

schedule.every().day.at("08:20").do(check_birthdays)


@bot.message_handler(commands=['broadcast_message'])
def broadcast_message(message):
    user_id = message.from_user.id

    if user_id != god_id:
        bot.send_message(user_id, "Эта команда доступна только владельцу!")
        return

    bot.send_message(user_id, "Введи сообщение, которое хочешь разослать всем пользователям:")
    bot.register_next_step_handler(message, send_broadcast)

def send_broadcast(message):
    user_id = message.from_user.id
    broadcast_text = message.text

    if not broadcast_text:
        bot.send_message(user_id, "Сообщение не может быть пустым!")
        return

    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()

    for user in users:
        try:
            bot.send_message(user[0], broadcast_text)
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {user[0]}: {e}")

    bot.send_message(user_id, "Сообщение успешно разослано всем пользователям.")
    

@bot.message_handler(commands=['show_homework'])
def show_homework(message):
    user_id = message.from_user.id

    if user_id != god_id:
        bot.send_message(user_id, "Эта команда доступна только владельцу!")
        return

    cursor.execute('SELECT id, subject FROM homework')
    homework_list = cursor.fetchall()

    if not homework_list:
        bot.send_message(user_id, "Домашних заданий пока нет.")
        return

    homework_message = "📚 Домашние задания:\n\n"
    for hw_id, subject in homework_list:
        homework_message += f"ID: {hw_id} ▫️ {subject}\n"
    bot.send_message(user_id, homework_message)


@bot.message_handler(commands=['message_admin'])
def ask_for_message(message):
    user_id = message.from_user.id
    msg = bot.send_message(user_id, "Введи сообщение, которое хотите отправить админу:")
    bot.register_next_step_handler(msg, forward_message_to_admin)

def forward_message_to_admin(message):
    user_message = message.text
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username

    admin_message = f"Сообщение от пользователя:\n\n" \
                    f"Имя: {user_name}\n" \
                    f"Username: @{username}\n" \
                    f"User ID: {user_id}\n\n" \
                    f"Сообщение: \n{user_message}"

    try:
        bot.send_message(god_id, admin_message)
        bot.send_message(user_id, "Админ получил твое сообщение!")
    except Exception as e:
        bot.send_message(user_id, "Произошла ошибка при отправке сообщения админу. Попробуй снова.")

@bot.message_handler(commands=['message_user'])
def ask_for_user_id(message):
    if message.from_user.id == god_id:
        msg = bot.send_message(god_id, "Введи ID пользователя, которому вы хотите отправить сообщение:")
        bot.register_next_step_handler(msg, ask_for_message_to_user)
    else:
        bot.send_message(message.from_user.id, "Эта команда доступна только владельцу бота.")

def ask_for_message_to_user(message):
    try:
        user_id = int(message.text)
        msg = bot.send_message(god_id, f"Введи сообщение для этого пользователя:")
        bot.register_next_step_handler(msg, send_message_to_user, user_id)
    except ValueError:
        bot.send_message(god_id, "Ошибка: Пожалуйста, введи правильный числовой ID пользователя.")

def send_message_to_user(message, user_id):
    admin_message = message.text
    try:
        bot.send_message(user_id, f"❗️Тебе пришло сообщение от администратора:\n\n{admin_message}")
        bot.send_message(god_id, f"Сообщение успешно отправлено пользователю!")
    except Exception as e:
        bot.send_message(god_id, f"Не удалось отправить сообщение пользователю с ID {user_id}. Скорее всего такого пользователя нет")

def get_bot_info():
    info = {}
    with open('bot_info.txt', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if ': ' in line:
                key, value = line.split(': ', 1) 
                info[key] = value
    return info

def get_uptime():
    uptime_seconds = int(time.time() - start_time)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    uptime_str = f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
    return uptime_str

@bot.message_handler(commands=['info'])
def send_info(message):
    info = get_bot_info()
    uptime = get_uptime()
    
    response = (f"📋 Версия бота: {info['version']}\n"
                f"🕒 Последнее изменение: {info['last_modified']}\n"
                f"📝 Журнал обновлений: {info['additional_info']}\n\n"
                f"⏳ Бот работает без перебоев: {uptime}")
    
    bot.send_message(message.chat.id, response)

def read_update_history():
    file_path = 'update_history.txt'
    if os.path.exists(file_path):
        if os.path.getsize(file_path) > 0:
            with open(file_path, 'r', encoding='utf-8') as file:
                return file.read()
        else:
            return "История обновлений отсутствует"
    return "История обновлений не найдена."

@bot.message_handler(commands=['update_history'])
def update_history(message):
    history = read_update_history()
    bot.send_message(message.chat.id, history)

check_unfinished_states()

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_query = message.text

    preparing_message = bot.reply_to(message, "⏳ Обдумываю ответ...")

    gpt_response = None
    for model in models:
        gpt_response = ask_gpt_with_timeout(model, user_query)
        if gpt_response:
            break

    if not gpt_response:
        gpt_response = "😴Что-то я сегодня не выспался, попробуй позже"

    try:
        bot.edit_message_text(chat_id=preparing_message.chat.id,
                              message_id=preparing_message.message_id,
                              text=gpt_response)
    except Exception as e:
        bot.send_message(chat_id=message.chat.id, text=gpt_response)


def close_connection():
    conn.close()

atexit.register(close_connection)

bot.polling()