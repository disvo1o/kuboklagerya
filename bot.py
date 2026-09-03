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

# твой Telegram ID
ADMIN_TELEGRAM_ID = 128835770

# максимальное количество участников
MAX_PARTICIPANTS = 64


# =========================
# СООБЩЕНИЯ
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

TOO_LONG_MESSAGE = (
    "ник слишком длинный. максимум 100 символов."
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


# =========================
# ПАМЯТЬ
# =========================

registered_users = set()

registration_lock = asyncio.Lock()


# =========================
# ПРОВЕРКА АДМИНА
# =========================

def is_admin(user_id):
    return user_id == ADMIN_TELEGRAM_ID


# =========================
# ЗАГРУЗКА РЕГИСТРАЦИЙ
# =========================

def get_registered_users_from_sheet():
    users = set()

    try:
        rows = sheet.get_all_values()

        for row in rows[1:]:
            if len(row) >= 4:
                telegram_id = row[3].strip()

                if telegram_id:
                    try:
                        users.add(int(telegram_id))
                    except ValueError:
                        pass

    except Exception as error:
        print(
            f"ошибка чтения google таблицы: {error}"
        )

    return users


def refresh_registered_users():
    global registered_users

    registered_users = (
        get_registered_users_from_sheet()
    )

    print(
        f"зарегистрировано: "
        f"{len(registered_users)}/{MAX_PARTICIPANTS}"
    )


# =========================
# /START
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    if user is None:
        return

    print(
        f"/start от пользователя "
        f"{user.id} (@{user.username})"
    )

    # =========================
    # АДМИН
    # =========================

    if is_admin(user.id):
        context.user_data[
            "waiting_for_nickname"
        ] = True

        await update.message.reply_text(
            WELCOME_MESSAGE
        )

        return

    # =========================
    # ОБНОВЛЯЕМ СПИСОК
    # ИЗ GOOGLE SHEETS
    # =========================

    await asyncio.to_thread(
        refresh_registered_users
    )

    # если уже зарегистрирован
    if user.id in registered_users:
        return

    # если все места заняты
    if len(registered_users) >= MAX_PARTICIPANTS:
        await update.message.reply_text(
            LIMIT_MESSAGE
        )

        return

    # ждем ник
    context.user_data[
        "waiting_for_nickname"
    ] = True

    await update.message.reply_text(
        WELCOME_MESSAGE
    )


# =========================
# ПОЛУЧЕНИЕ НИКА
# =========================

async def receive_nickname(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user = update.effective_user

    if user is None:
        return

    if update.message is None:
        return

    if update.message.text is None:
        return

    # если бот не ждет ник
    if not context.user_data.get(
        "waiting_for_nickname",
        False
    ):
        return

    nickname = update.message.text.strip()

    if not nickname:
        return

    # ограничение ника
    if len(nickname) > 100:
        await update.message.reply_text(
            TOO_LONG_MESSAGE
        )

        return

    # =========================
    # БЛОКИРУЕМ ОДНОВРЕМЕННЫЕ
    # РЕГИСТРАЦИИ
    # =========================

    async with registration_lock:

        # =========================
        # СВЕЖАЯ ПРОВЕРКА ТАБЛИЦЫ
        # =========================

        await asyncio.to_thread(
            refresh_registered_users
        )

        # =========================
        # ОБЫЧНЫЙ ПОЛЬЗОВАТЕЛЬ
        # =========================

        if not is_admin(user.id):

            # пользователь уже зарегистрирован
            if user.id in registered_users:
                context.user_data[
                    "waiting_for_nickname"
                ] = False

                return

            # все места заняты
            if len(registered_users) >= MAX_PARTICIPANTS:
                context.user_data[
                    "waiting_for_nickname"
                ] = False

                await update.message.reply_text(
                    LIMIT_MESSAGE
                )

                return

        # =========================
        # ДАННЫЕ TELEGRAM
        # =========================

        telegram_username = (
            "@" + user.username
            if user.username
            else ""
        )

        telegram_name = " ".join(
            part
            for part in [
                user.first_name,
                user.last_name
            ]
            if part
        )

        registration_date = (
            datetime.now().strftime(
                "%d.%m.%Y %H:%M:%S"
            )
        )

        # =========================
        # СТРОКА ДЛЯ ТАБЛИЦЫ
        # =========================

        row = [
            telegram_username,
            telegram_name,
            nickname,
            str(user.id),
            registration_date,
        ]

        # =========================
        # ЗАПИСЫВАЕМ
        # =========================

        await asyncio.to_thread(
            sheet.append_row,
            row,
            value_input_option="USER_ENTERED"
        )

        # =========================
        # ОБНОВЛЯЕМ СПИСОК
        # =========================

        await asyncio.to_thread(
            refresh_registered_users
        )

        # администратор не занимает место
        if not is_admin(user.id):
            registered_users.add(user.id)

        # больше не ждем сообщение
        context.user_data[
            "waiting_for_nickname"
        ] = False

        # =========================
        # СКОЛЬКО МЕСТ ОСТАЛОСЬ
        # =========================

        remaining_places = (
            MAX_PARTICIPANTS
            - len(registered_users)
        )

    # =========================
    # ОТВЕТ УЧАСТНИКУ
    # =========================

    await update.message.reply_text(
        SUCCESS_MESSAGE
    )

    # =========================
    # УВЕДОМЛЕНИЕ ТЕБЕ
    # =========================

    if not is_admin(user.id):

        username_text = (
            f"@{user.username}"
            if user.username
            else "без username"
        )

        admin_message = (
            "зарегистрирован новый участник!\n\n"
            f"имя: {telegram_name}\n"
            f"username: {username_text}\n"
            f"ник на турнире: {nickname}\n\n"
            f"осталось мест: {remaining_places} из "
            f"{MAX_PARTICIPANTS}"
        )

        try:
            await context.bot.send_message(
                chat_id=ADMIN_TELEGRAM_ID,
                text=admin_message
            )

        except Exception as error:
            print(
                f"ошибка отправки уведомления "
                f"администратору: {error}"
            )


# =========================
# ЗАПУСК
# =========================

def main():

    print("запускаем бота...")

    refresh_registered_users()

    print(
        f"свободных мест: "
        f"{MAX_PARTICIPANTS - len(registered_users)}"
    )

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # обычные сообщения
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_nickname
        )
    )

    print("бот запущен!")

    application.run_polling()


if __name__ == "__main__":
    main()
