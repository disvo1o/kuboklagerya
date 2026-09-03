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
# настройки
# =========================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

MAX_PARTICIPANTS = 64


# =========================
# сообщения
# =========================

WELCOME_MESSAGE = (
    "добро пожаловать на кубок лагеря!\n\n"
    "напиши ниже ник, под которым ты будешь участвовать в турнире."
)

SUCCESS_MESSAGE = (
    "ты зарегистрирован! ждем тебя в 12:00 на главной сцене! "
    "не опаздывай!"
)

LIMIT_MESSAGE = (
    "регистрация завершена — все 64 места уже заняты."
)


# =========================
# подключение к google sheets
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


# =========================
# зарегистрированные пользователи
# =========================

registered_users = set()

registration_lock = asyncio.Lock()


def load_registered_users():
    try:
        rows = sheet.get_all_values()

        for row in rows[1:]:
            if len(row) >= 4:
                telegram_id = row[3].strip()

                if telegram_id:
                    try:
                        registered_users.add(int(telegram_id))
                    except ValueError:
                        pass

        print(
            f"загружено зарегистрированных пользователей: "
            f"{len(registered_users)}"
        )

    except Exception as error:
        print(f"ошибка загрузки таблицы: {error}")


# =========================
# команда /start
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    # если пользователь уже зарегистрирован —
    # полностью игнорируем его
    if user.id in registered_users:
        return

    # если все места заняты
    if len(registered_users) >= MAX_PARTICIPANTS:
        await update.message.reply_text(LIMIT_MESSAGE)
        return

    # ждем ник
    context.user_data["waiting_for_nickname"] = True

    await update.message.reply_text(WELCOME_MESSAGE)


# =========================
# получение ника
# =========================

async def receive_nickname(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    # если пользователь уже зарегистрирован —
    # ничего не делаем
    if user.id in registered_users:
        return

    # если бот сейчас не ждет ник
    if not context.user_data.get("waiting_for_nickname"):
        return

    nickname = update.message.text.strip()

    # пустой ник
    if not nickname:
        return

    # ограничение длины ника
    if len(nickname) > 100:
        await update.message.reply_text(
            "ник слишком длинный. максимум 100 символов."
        )
        return

    # блокируем регистрацию,
    # чтобы одновременно не зарегистрировалось
    # больше 64 человек
    async with registration_lock:

        # повторная проверка
        if user.id in registered_users:
            return

        # проверяем лимит непосредственно перед записью
        if len(registered_users) >= MAX_PARTICIPANTS:
            context.user_data["waiting_for_nickname"] = False

            await update.message.reply_text(LIMIT_MESSAGE)
            return

        # telegram username
        telegram_username = (
            "@" + user.username
            if user.username
            else ""
        )

        # имя пользователя telegram
        telegram_name = " ".join(
            part
            for part in [
                user.first_name,
                user.last_name
            ]
            if part
        )

        # дата регистрации
        registration_date = datetime.now().strftime(
            "%d.%m.%Y %H:%M:%S"
        )

        # строка для google sheets
        row = [
            telegram_username,
            telegram_name,
            nickname,
            str(user.id),
            registration_date,
        ]

        # записываем пользователя в таблицу
        await asyncio.to_thread(
            sheet.append_row,
            row,
            value_input_option="USER_ENTERED"
        )

        # добавляем пользователя в список зарегистрированных
        registered_users.add(user.id)

        # больше ничего от него не ждем
        context.user_data["waiting_for_nickname"] = False

    # подтверждение регистрации
    await update.message.reply_text(SUCCESS_MESSAGE)


# =========================
# запуск бота
# =========================

def main():
    print("запускаем бота...")

    # загружаем уже зарегистрированных пользователей
    load_registered_users()

    # создаем приложение telegram
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # команда /start
    application.add_handler(
        CommandHandler("start", start)
    )

    # обычные текстовые сообщения
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_nickname
        )
    )

    print("бот запущен!")

    # запускаем бота
    application.run_polling()


if __name__ == "__main__":
    main()
