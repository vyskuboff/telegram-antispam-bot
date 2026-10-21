import asyncio
import logging
import tempfile
import uuid
import zipfile
from html import escape
from pathlib import Path

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeChatAdministrators,
    BotCommandScopeDefault,
    BufferedInputFile,
    ChatPermissions,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from app.config import ADMIN_IDS, BOT_TOKEN, DATA_DIR, GROUP_IDS, SPAM_USER_IDS, WHITE_LIST_IDS, validate_config
from app.filters import spam_reason
from app.storage import (
    add_pending_user, add_stop_word_db, backup_database, delete_last_block_entry,
    delete_pending_user, delete_stop_word_db, get_pending_user, get_stop_words,
    init_db, list_pending_users, load_last_block, register_private_contact_message,
    save_last_block_entry, update_pending_attempt,
)


logger = logging.getLogger(__name__)
dp = Dispatcher()
bot = None
LAST_BLOCK = {}
LAST_WORD_ACTION = {}
ACTIVE_VERIFICATIONS = {}
USER_LOCKS = {}

VERIFICATION_TIMEOUT_SECONDS = 7
MAX_VERIFICATION_ATTEMPTS = 5


def user_lock(key):
    return USER_LOCKS.setdefault(key, asyncio.Lock())


def new_token():
    return uuid.uuid4().hex[:16]


def user_info(user):
    name = " ".join(part for part in (user.first_name, user.last_name) if part)
    username = f"@{user.username}" if user.username else "нет"
    return f"Пользователь: {escape(name or 'Unknown')}\nID: {user.id}\nUsername: {escape(username)}"


def chat_info(chat):
    title = (chat.title or "").strip()
    if len(title) > 50:
        title = title[:50] + "…"
    parts = [escape(title)] if title else []
    if chat.username:
        parts.append("@" + escape(chat.username))
    parts.append(f"ID: {chat.id}")
    return " | ".join(parts)


def muted_permissions():
    return ChatPermissions(
        can_send_messages=False, can_send_audios=False,
        can_send_documents=False, can_send_photos=False,
        can_send_videos=False, can_send_video_notes=False,
        can_send_voice_notes=False, can_send_polls=False,
        can_send_other_messages=False, can_add_web_page_previews=False,
        can_invite_users=False,
    )


async def try_delete(chat_id, message_id):
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        logger.warning("Could not delete message %s in chat %s", message_id, chat_id, exc_info=True)


async def notify_admins(text, *, silent=False):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, disable_notification=silent)
        except TelegramAPIError:
            logger.warning("Could not notify admin %s", admin_id, exc_info=True)


async def clear_verification(key, *, delete_prompts=True, delete_user_message=False):
    entry = ACTIVE_VERIFICATIONS.pop(key, None)
    if not entry:
        return
    entry["task"].cancel()
    if delete_prompts:
        await try_delete(key[0], entry["bot_msg_id"])
    if delete_user_message:
        await try_delete(key[0], entry["user_msg_id"])


async def clear_block_suggestion(key):
    entry = LAST_BLOCK.pop(key, None)
    delete_last_block_entry(*key)
    if entry:
        for admin_id, message_id in entry["messages"].items():
            await try_delete(admin_id, message_id)


async def send_block_suggestion(user, chat, reply_map):
    key = (chat.id, user.id)
    await clear_block_suggestion(key)
    token = new_token()
    buttons = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Ограничить", callback_data=f"block:{chat.id}:{user.id}:{token}"),
        InlineKeyboardButton(text="Отмена", callback_data=f"cancel_block:{chat.id}:{user.id}:{token}"),
    ]])
    text = f"Предложение ограничения\n\n{user_info(user)}\nЧат: {chat_info(chat)}"
    messages = {}
    for admin_id, reply_to in reply_map.items():
        try:
            sent = await bot.send_message(
                admin_id, text, reply_to_message_id=reply_to, reply_markup=buttons
            )
            messages[admin_id] = sent.message_id
        except TelegramAPIError:
            logger.warning("Could not send restriction suggestion to %s", admin_id, exc_info=True)
    if messages:
        LAST_BLOCK[key] = {"token": token, "messages": messages}
        save_last_block_entry(*key, token, messages)


async def forward_and_notify(chat_id, user, chat, message_id, reason, *, with_buttons=True):
    info = f"{escape(reason[:500])}\n{user_info(user)}\nЧат: {chat_info(chat)}"
    forwarded = {}
    for admin_id in ADMIN_IDS:
        reply_to = None
        try:
            sent = await bot.forward_message(admin_id, chat_id, message_id)
            reply_to = sent.message_id
        except TelegramAPIError:
            logger.warning("Could not forward message %s to %s", message_id, admin_id, exc_info=True)
        try:
            await bot.send_message(admin_id, info, reply_to_message_id=reply_to)
        except TelegramAPIError:
            logger.warning("Could not notify admin %s", admin_id, exc_info=True)
        if reply_to is not None:
            forwarded[admin_id] = reply_to
    if with_buttons:
        await send_block_suggestion(user, chat, forwarded)


async def delete_with_forward(message, reason, *, with_buttons=True):
    await forward_and_notify(
        message.chat.id, message.from_user, message.chat, message.message_id,
        reason, with_buttons=with_buttons,
    )
    await try_delete(message.chat.id, message.message_id)


async def restrict_user(chat_id, user_id):
    try:
        await bot.restrict_chat_member(chat_id, user_id, permissions=muted_permissions())
        return True
    except TelegramAPIError:
        logger.exception("Could not restrict user %s in chat %s", user_id, chat_id)
        return False


async def verification_timeout(key, token):
    try:
        await asyncio.sleep(VERIFICATION_TIMEOUT_SECONDS)
        async with user_lock(key):
            entry = ACTIVE_VERIFICATIONS.get(key)
            if not entry or entry["token"] != token:
                return

            ACTIVE_VERIFICATIONS.pop(key, None)
            chat_id, user_id = key
            await try_delete(chat_id, entry["bot_msg_id"])

            # Timeout removes only the bot prompt. The user stays pending and
            # the attempt counter is preserved until they verify or are blocked.
            pending = get_pending_user(chat_id, user_id)
            if pending and pending["message_id"] == entry["bot_msg_id"]:
                update_pending_attempt(
                    chat_id, user_id, pending["attempts"], None
                )
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("Verification timeout failed for %s", key)


@dp.message(F.chat.id.in_(GROUP_IDS))
async def handle_all_messages(message: types.Message):
    # Keep managed groups clean: join/leave service messages are redundant
    # because admins receive a richer notification through chat_member updates.
    if message.new_chat_members or message.left_chat_member:
        await try_delete(message.chat.id, message.message_id)
        return

    user = message.from_user
    if not user or user.is_bot or user.id in WHITE_LIST_IDS:
        return
    if (message.group_chat_created or message.supergroup_chat_created
            or message.channel_chat_created):
        return

    key = (message.chat.id, user.id)
    async with user_lock(key):
        pending = get_pending_user(*key)
        if pending:
            # Every message from a pending user is checked for spam first.
            text = message.text or message.caption or ""
            reason = spam_reason(text, set(get_stop_words()))

            # Only one verification prompt may exist per user. Never delete a
            # previous normal user message when replacing the prompt.
            await clear_verification(key, delete_user_message=False)

            attempts_done = int(pending["attempts"])

            # Five prompts have already been issued. The next (6th) message
            # means the user ignored all five verification attempts. The 6th
            # message itself follows the ordinary spam rules: keep it if it is
            # clean, forward/delete it only if it is spam.
            if attempts_done >= MAX_VERIFICATION_ATTEMPTS:
                if reason:
                    await delete_with_forward(
                        message,
                        "Новый пользователь отправил спам перед автоматическим "
                        "ограничением: " + reason,
                        with_buttons=False,
                    )

                if await restrict_user(*key):
                    delete_pending_user(*key)
                    await clear_block_suggestion(key)

                    mention = (
                        "@" + escape(user.username)
                        if user.username
                        else escape(user.first_name or f"ID {user.id}")
                    )
                    try:
                        await bot.send_message(
                            key[0],
                            f"{mention} ограничен: не пройдена проверка «Я не бот» "
                            f"за {MAX_VERIFICATION_ATTEMPTS} попыток.",
                            disable_notification=True,
                        )
                    except TelegramAPIError:
                        logger.warning(
                            "Could not send automatic restriction notice for %s",
                            key,
                            exc_info=True,
                        )

                    await notify_admins(
                        "Пользователь автоматически ОГРАНИЧЕН\n\n"
                        f"{user_info(user)}\n"
                        f"Чат: {chat_info(message.chat)}\n"
                        "Статус: ограничен (restricted)\n"
                        f"Причина: не пройдена проверка за "
                        f"{MAX_VERIFICATION_ATTEMPTS} попыток",
                        silent=True,
                    )
                else:
                    # Keep the user pending so the next message retries the
                    # restriction instead of silently turning them ordinary.
                    update_pending_attempt(*key, attempts_done, None)
                return

            if reason:
                await delete_with_forward(
                    message,
                    "Новый пользователь отправил спам при проверке: " + reason,
                )

            attempt = attempts_done + 1
            mention = (
                "@" + user.username
                if user.username
                else (user.first_name or f"ID {user.id}")
            )
            token = new_token()
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="Я не бот",
                    callback_data=f"verify:{key[0]}:{key[1]}:{token}",
                )
            ]])

            try:
                prompt = await bot.send_message(
                    key[0],
                    f"{escape(mention)}, нажмите кнопку в течение "
                    f"{VERIFICATION_TIMEOUT_SECONDS} секунд.\n"
                    f"Попытка {attempt}/{MAX_VERIFICATION_ATTEMPTS}",
                    reply_markup=keyboard,
                    disable_notification=True,
                )
            except TelegramAPIError:
                logger.exception("Could not send verification prompt for %s", key)
                return

            update_pending_attempt(*key, attempt, prompt.message_id)
            task = asyncio.create_task(verification_timeout(key, token))
            ACTIVE_VERIFICATIONS[key] = {
                "token": token,
                "bot_msg_id": prompt.message_id,
                "user_msg_id": message.message_id,
                "task": task,
            }
            return

        if user.id in SPAM_USER_IDS:
            await try_delete(message.chat.id, message.message_id)
            return

        reason = spam_reason(
            message.text or message.caption or "",
            set(get_stop_words()),
        )
        if reason:
            await delete_with_forward(message, reason)


@dp.edited_message(F.chat.id.in_(GROUP_IDS))
async def handle_edited_message(message: types.Message):
    user = message.from_user
    if not user or user.is_bot or user.id in WHITE_LIST_IDS:
        return
    key = (message.chat.id, user.id)
    async with user_lock(key):
        if user.id in SPAM_USER_IDS:
            await try_delete(message.chat.id, message.message_id)
            return
        if get_pending_user(*key):
            return
        reason = spam_reason(message.text or message.caption or "", set(get_stop_words()))
        if reason:
            await delete_with_forward(message, "Сообщение было отредактировано и стало спамом: " + reason)


def chat_member_status_value(status):
    return getattr(status, "value", str(status))


def chat_member_is_present(member):
    status = chat_member_status_value(member.status)

    if status in ("left", "kicked"):
        return False

    if status == "restricted":
        return bool(getattr(member, "is_member", False))

    return True


def chat_member_status_text(status):
    labels = {
        "creator": "владелец (creator)",
        "administrator": "администратор (administrator)",
        "member": "участник (member)",
        "restricted": "ограничен (restricted)",
        "left": "вышел (left)",
        "kicked": "заблокирован (kicked)",
    }
    return labels.get(status, status)


@dp.chat_member()
async def handle_chat_member(event: types.ChatMemberUpdated):
    if event.chat.id not in GROUP_IDS:
        return

    user = event.new_chat_member.user
    key = (event.chat.id, user.id)
    old = chat_member_status_value(event.old_chat_member.status)
    new = chat_member_status_value(event.new_chat_member.status)
    old_present = chat_member_is_present(event.old_chat_member)
    new_present = chat_member_is_present(event.new_chat_member)

    # Restricted users can enter/leave while their status remains "restricted".
    # Telegram represents that transition through ChatMemberRestricted.is_member.
    joined = not old_present and new_present
    if joined:
        async with user_lock(key):
            await clear_verification(key)
            await clear_block_suggestion(key)

            if user.id in WHITE_LIST_IDS or user.is_bot:
                return

            if new == "member":
                add_pending_user(*key)
                state_line = "Статус: новый пользователь, ожидает проверку"
            elif new == "restricted":
                delete_pending_user(*key)
                state_line = "Статус: ограничен (restricted)"
            else:
                delete_pending_user(*key)
                state_line = f"Статус: {chat_member_status_text(new)}"

        await notify_admins(
            f"Пользователь вошёл в чат\n\n{user_info(user)}\n"
            f"Чат: {chat_info(event.chat)}\n{state_line}",
            silent=True,
        )
        return

    # Report every real leave/ban transition. For restricted users this also
    # catches restricted(is_member=True) -> restricted(is_member=False).
    left = old_present and not new_present
    if left:
        async with user_lock(key):
            pending = get_pending_user(*key)
            await clear_verification(key)
            delete_pending_user(*key)

        status_text = (
            "Пользователь вышел во время проверки"
            if pending
            else "Пользователь вышел из чата"
        )
        await notify_admins(
            f"{status_text}\n\n{user_info(user)}\n"
            f"Чат: {chat_info(event.chat)}\n"
            f"Статус до выхода: {chat_member_status_text(old)}\n"
            f"Новый статус: {chat_member_status_text(new)}",
            silent=True,
        )


@dp.message(F.chat.type == ChatType.PRIVATE, F.from_user.id.in_(ADMIN_IDS), F.text)
async def handle_admin_private(message: types.Message):
    text = message.text.strip()
    if text == "/start":
        await message.answer(
            "Приветствую! Это антиспам бот.\n\n"
            "/show_all_words — список стоп-слов\n/reserv — резервная копия базы\n\n"
            "Отправь одно слово, чтобы добавить или удалить его."
        )
        return
    if text == "/show_all_words":
        words = get_stop_words()
        if not words:
            await message.answer("Список стоп-слов пуст.")
            return
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "stop_words.txt"
            path.write_text("\n".join(words), encoding="utf-8")
            await message.answer_document(FSInputFile(path), caption="Список стоп-слов")
        return
    if text == "/reserv":
        try:
            # Build the SQLite snapshot and ZIP first, then detach the archive
            # from temporary files. This avoids Windows cleanup/file-handle races
            # with FSInputFile after Telegram has already accepted the upload.
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
                snapshot = Path(temp_dir) / "state.db"
                archive = Path(temp_dir) / "backup.zip"
                backup_database(snapshot)
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    zf.write(snapshot, arcname="state.db")
                archive_bytes = archive.read_bytes()
        except Exception:
            logger.exception("Could not create database backup")
            await message.answer("Ошибка при создании резервной копии.")
            return

        try:
            await message.answer_document(
                BufferedInputFile(archive_bytes, filename="backup.zip"),
                caption="Резервная копия базы",
            )
        except TelegramAPIError:
            logger.exception("Could not send database backup")
            await message.answer("Резервная копия создана, но не удалось отправить файл.")
        return
    if text.startswith("/"):
        await message.answer("Неизвестная команда. Напиши /start.")
        return
    if len(text.split()) != 1 or len(text) > 100 or not text.isalnum():
        await message.answer("Пришли одно слово из букв или цифр (до 100 символов).")
        return
    word = text.lower()
    token = new_token()
    action = "delete" if word in get_stop_words() else "add"
    LAST_WORD_ACTION[message.from_user.id] = (token, word, action)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="Удалить стоп-слово" if action == "delete" else "Добавить стоп-слово",
            callback_data=f"word:{action}:{token}",
        ),
        InlineKeyboardButton(text="Отмена", callback_data=f"word:cancel:{token}"),
    ]])
    await message.answer(f"Слово «{escape(word)}». Подтвердить действие?", reply_markup=keyboard)


@dp.message(F.chat.type == ChatType.PRIVATE)
async def handle_non_admin_private(message: types.Message):
    user = message.from_user
    if not user or user.is_bot or user.id in ADMIN_IDS:
        return

    # Reserve one of the first three forwarding slots atomically. This prevents
    # a burst of simultaneous messages from forwarding more than three times.
    message_number = register_private_contact_message(user.id, max_forwarded=3)
    if message_number is None:
        return

    info = (
        f"Личное сообщение боту от не-админа — {message_number}/3\n\n"
        f"{user_info(user)}\n"
        + (
            "Будут пересланы только первые 3 сообщения этого пользователя."
            if message_number == 1
            else (
                "После следующего сообщения бот будет полностью игнорировать "
                "этого пользователя в ЛС."
                if message_number == 2
                else "Лимит достигнут. Все дальнейшие сообщения будут игнорироваться."
            )
        )
    )

    for admin_id in ADMIN_IDS:
        forwarded_message_id = None
        try:
            forwarded = await message.forward(admin_id)
            forwarded_message_id = forwarded.message_id
        except TelegramAPIError:
            logger.warning(
                "Could not forward private message %s/3 from user %s to admin %s",
                message_number,
                user.id,
                admin_id,
                exc_info=True,
            )

        try:
            await bot.send_message(
                admin_id,
                info,
                reply_to_message_id=forwarded_message_id,
                disable_notification=True,
            )
        except TelegramAPIError:
            logger.warning(
                "Could not notify admin %s about private user %s",
                admin_id,
                user.id,
                exc_info=True,
            )


@dp.callback_query(F.data.startswith("word:"))
async def process_word(query: types.CallbackQuery):
    if query.from_user.id not in ADMIN_IDS or not query.message or query.message.chat.type != ChatType.PRIVATE:
        return await query.answer("Нет прав", show_alert=True)
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        return await query.answer("Некорректная кнопка", show_alert=True)
    _, action, token = parts
    saved = LAST_WORD_ACTION.get(query.from_user.id)
    if not saved or saved[0] != token or action not in (saved[2], "cancel"):
        return await query.answer("Контекст устарел", show_alert=True)
    LAST_WORD_ACTION.pop(query.from_user.id, None)
    if action == "cancel":
        reply = "Отменено"
    elif action == "add":
        added = add_stop_word_db(saved[1])
        reply = "Слово добавлено." if added else "Слово уже есть в списке."
    else:
        deleted = delete_stop_word_db(saved[1])
        reply = "Слово удалено." if deleted else "Слова уже нет в списке."
    await try_delete(query.message.chat.id, query.message.message_id)
    await query.answer(reply, show_alert=True)


def parse_user_callback(query, prefix):
    parts = (query.data or "").split(":")
    if len(parts) != 4 or parts[0] != prefix or len(parts[3]) != 16:
        return None
    try:
        return (int(parts[1]), int(parts[2])), parts[3]
    except ValueError:
        return None


@dp.callback_query(F.data.startswith("verify:"))
async def process_verify(query: types.CallbackQuery):
    parsed = parse_user_callback(query, "verify")
    if not parsed or not query.message:
        return await query.answer("Некорректная кнопка", show_alert=True)
    key, token = parsed
    if query.from_user.id != key[1]:
        return await query.answer("Это не для тебя", show_alert=True)
    if query.message.chat.id != key[0]:
        return await query.answer("Контекст устарел", show_alert=True)
    async with user_lock(key):
        active = ACTIVE_VERIFICATIONS.get(key)
        pending = get_pending_user(*key)
        if (not active or not pending or active["token"] != token
                or active["bot_msg_id"] != query.message.message_id
                or pending["message_id"] != query.message.message_id):
            return await query.answer("Проверка завершена или недействительна", show_alert=True)
        await clear_verification(key)
        delete_pending_user(*key)
        try:
            chat = await bot.get_chat(key[0])
            chat_line = chat_info(chat)
        except TelegramAPIError:
            logger.warning("Could not fetch chat %s after verification", key[0], exc_info=True)
            chat_line = f"ID: {key[0]}"
        await notify_admins(
            f"Пользователь прошёл проверку\n\n{user_info(query.from_user)}\nЧат: {chat_line}"
        )
        await query.answer("Проверка пройдена", show_alert=True)


async def process_block_action(query, action):
    if query.from_user.id not in ADMIN_IDS:
        return await query.answer("Нет прав", show_alert=True)
    parsed = parse_user_callback(query, action)
    if not parsed or not query.message or query.message.chat.id != query.from_user.id:
        return await query.answer("Некорректная кнопка", show_alert=True)
    key, token = parsed
    async with user_lock(key):
        entry = LAST_BLOCK.get(key)
        if (not entry or entry["token"] != token
                or entry["messages"].get(query.from_user.id) != query.message.message_id):
            return await query.answer("Контекст устарел", show_alert=True)
        if action == "block":
            if not await restrict_user(*key):
                return await query.answer(
                    "Не удалось ограничить пользователя",
                    show_alert=True,
                )

            await clear_verification(key, delete_user_message=False)
            delete_pending_user(*key)
            await clear_block_suggestion(key)

            try:
                member = await bot.get_chat_member(*key)
                name = user_info(member.user)
            except TelegramAPIError:
                name = f"ID пользователя: {key[1]}"

            await notify_admins(
                f"Пользователь ОГРАНИЧЕН\n\n{name}\nЧат: {key[0]}\n"
                "Статус: ограничен (restricted)\n"
                f"Админ: {escape(query.from_user.first_name or '')} "
                f"(ID: {query.from_user.id})",
                silent=True,
            )
            reply = "Пользователь полностью ограничен"
        else:
            # Cancel only the admin restriction suggestion. It must not cancel
            # the user's pending «Я не бот» verification state.
            await clear_block_suggestion(key)
            reply = "Отменено"

        await query.answer(reply, show_alert=True)


@dp.callback_query(F.data.startswith("block:"))
async def process_block_callback(query: types.CallbackQuery):
    await process_block_action(query, "block")


@dp.callback_query(F.data.startswith("cancel_block:"))
async def process_cancel_block_callback(query: types.CallbackQuery):
    await process_block_action(query, "cancel_block")


async def cleanup_restricted_users():
    for row in list_pending_users():
        key = (row["chat_id"], row["user_id"])
        async with user_lock(key):
            try:
                member = await bot.get_chat_member(*key)
            except TelegramAPIError:
                logger.warning("Could not check pending member %s", key, exc_info=True)
                continue
            if member.status in ("left", "kicked"):
                await clear_verification(key)
                delete_pending_user(*key)


async def daily_cleanup():
    while True:
        await asyncio.sleep(86400)
        try:
            await cleanup_restricted_users()
        except Exception:
            logger.exception("Daily cleanup failed")


async def clear_registered_bot_commands():
    """Remove command suggestions left by BotFather or older bot versions."""
    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]

    for chat_id in GROUP_IDS:
        scopes.append(BotCommandScopeChat(chat_id=chat_id))
        scopes.append(BotCommandScopeChatAdministrators(chat_id=chat_id))

    for scope in scopes:
        try:
            await bot.delete_my_commands(scope=scope)
        except TelegramAPIError:
            logger.warning(
                "Could not clear bot commands for scope %s",
                scope.type,
                exc_info=True,
            )


async def main():
    global bot, LAST_BLOCK
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    validate_config()
    init_db()
    LAST_BLOCK = load_last_block()
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    cleanup_task = None
    try:
        me = await bot.get_me()
        logger.info("Bot @%s started", me.username)
        await clear_registered_bot_commands()
        await cleanup_restricted_users()
        cleanup_task = asyncio.create_task(daily_cleanup())
        await dp.start_polling(bot)
    finally:
        if cleanup_task:
            cleanup_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Normal foreground shutdown requested by the operator.
        pass
