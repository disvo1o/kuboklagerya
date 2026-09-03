import os
import json
import asyncio
from datetime import datetime

import gspread
from google.oauth2.service_account import Credentials

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================
# НАСТРОЙКИ
# =========================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

WELCOME_MESSAGE = (
    "Добро пожаловать на Кубок лагеря!\n\n"
    "Напиши ниже ник, под которым ты будешь участвовать в турнире."
)

SUCCESS_MESSAGE = (
    "Ты зарегистрирован! Ждем тебя в 12:00 на главной сцене! "
    "Не опаздывай!"
)


# =========================
# GOOGLE SHEETS
# =========================

def connect_to_sheet():
    data = json.loads(GOOGLE_JSON)

    credentials = Credentials.from_service_account_info(
        data,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )

    client = gspread.authorize(credentials)

    spreadsheet = client.open_by_key(SHEET_ID)

    return spreadsheet.sheet1


sheet = connect_to_sheet()


# Здесь храним ID уже зарегистрированных людей
registered_users = set()

# Защита от одновременных регистраций
registration_lock = asyncio.Lock()


def load_registered_users():
    """
    При запуске читаем таблицу и запоминаем,
    кто уже зарегистрирован.
    """

    try:
        rows = sheet.get_all_values()

        # Первая строка — заголовки
        for row in rows[1:]:
            if len(row) >= 4:
                telegram_id = row[3].strip()

                if telegram_id:
                    try:
                        registered_users.add(int(telegram_id))
                    except ValueError:
                        pass

        print(
            f"Загружено зарегистрированных пользователей: "
            f"{len(registered_users)}"
        )

    except Exception as error:
        print(f"Ошибка загрузки таблицы: {error}")


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    # Если уже регистрировался — ничего не отвечаем
    if user.id in registered_users:
        return

    # Запоминаем, что сейчас ждём ник
    context.user_data["waiting_for_nickname"] = True

    await update.message.reply_text(WELCOME_MESSAGE)


# =========================
# ПОЛУЧЕНИЕ НИКА
# =========================

async def receive_nickname(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    # Уже зарегистрирован — полностью игнорируем
    if user.id in registered_users:
        return

    # Мы не просили этого пользователя вводить ник
    if not context.user_data.get("waiting_for_nickname"):
        return

    nickname = update.message.text.strip()

    if not nickname:
        return

    # Ограничиваем длину ника
    if len(nickname) > 100:
        await update.message.reply_text(
            "Ник слишком длинный. Максимум 100 символов."
        )
        return

    async with registration_lock:

        # Проверяем ещё раз на случай
        # двух быстрых сообщений подряд
        if user.id in registered_users:
            return

        # Telegram username
        if user.username:
            telegram_username = "@" + user.username
        else:
            telegram_username = ""

        # Имя + фамилия Telegram
        telegram_name = " ".join(
            part
            for part in [
                user.first_name,
                user.last_name
            ]
            if part
        )

        # Время регистрации
        registration_date = datetime.now().strftime(
            "%d.%m.%Y %H:%M:%S"
        )

        # Строка для Google Sheets
        row = [
            telegram_username,
            telegram_name,
            nickname,
            str(user.id),
            registration_date,
        ]

        # Записываем в таблицу
        await asyncio.to_thread(
            sheet.append_row,
            row,
            value_input_option="USER_ENTERED"
        )

        # Помечаем пользователя зарегистрированным
        registered_users.add(user.id)

        context.user_data["waiting_for_nickname"] = False

    # Отправляем подтверждение
    await update.message.reply_text(SUCCESS_MESSAGE)


# =========================
# ЗАПУСК
# =========================

def main():

    print("Запускаем бота...")

    # Загружаем уже существующие регистрации
    load_registered_users()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Команда /start
    application.add_handler(
        CommandHandler("start", start)
    )

    # Обычные текстовые сообщения
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_nickname
        )
    )

    print("Бот запущен!")

    application.run_polling()


if __name__ == "__main__":
    main()
