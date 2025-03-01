import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import requests
import time
from threading import Thread, Lock
import logging
import os
import random
import http.server
import socketserver
from solana.rpc.websocket_api import connect
from solana.rpc.api import Client
import json
from base64 import b64decode
import asyncio

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Твой Telegram Bot токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения!")

# Фиктивный HTTP-сервер для Render
PORT = int(os.getenv("PORT", 8443))  # Render использует переменную PORT, по умолчанию 8443

def start_dummy_server():
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        logger.info(f"Фиктивный сервер запущен на порту {PORT}")
        httpd.serve_forever()

# Запускаем фиктивный сервер в отдельном потоке
dummy_server_thread = Thread(target=start_dummy_server, daemon=True)
dummy_server_thread.start()

# Словарь для хранения кошельков с синхронизацией
tracked_wallets = {}
wallet_lock = Lock()  # Для синхронизации доступа к tracked_wallets

# Словарь для хранения состояния потоков
monitoring_threads = {}

# Временное хранилище для состояния
user_states = {}

# Telegram бот
updater = Updater(BOT_TOKEN, use_context=True)
bot = updater.bot

# Курс SOL в USD (для теста, нужно получать через API, например, CoinGecko)
SOL_TO_USD = 137.0  # Пример: 1 SOL = 137 USD (как на скриншоте)

# Solana WebSocket клиент
SOLANA_WS_URL = "wss://api.mainnet-beta.solana.com"
SOLANA_HTTP_URL = "https://api.mainnet-beta.solana.com"
solana_client = Client(SOLANA_HTTP_URL)

# Программы для отслеживания
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623DQ5x"  # SPL Token Program
JUPITER_PROGRAM_ID = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTp1"  # Jupiter Aggregator
PUMP_FUN_PROGRAM_ID = "6EF8rrecthR5DkcocFusWxY6dvdTQXThK6JVZSJ1C1"  # Pump Fun
RAYDIUM_PROGRAM_ID = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"  # Raydium

# Подписка на транзакции через WebSocket (для программ)
async def monitor_program_ws(address, name, types, chat_id, program_id):
    async with connect(SOLANA_WS_URL) as ws:
        # Даём задержку для инициализации WebSocket
        await asyncio.sleep(5)

        # Подписываемся на транзакции программы
        await ws.program_subscribe(program_id)
        first_resp = await ws.recv()
        subscription_id = first_resp.result
        logger.info(f"Подписка на программу {program_id} для кошелька {name} ({address}) успешна, ID подписки: {subscription_id}")

        error_notified = False  # Флаг для отслеживания ошибок
        try:
            async for msg in ws:
                # Парсим сообщение от WebSocket
                try:
                    data = msg.result
                    if not data:
                        if not error_notified:
                            bot.send_message(chat_id=chat_id, text=f"Кошелек {name} ({address}) неактивен или не имеет транзакций для программы {program_id}.")
                            error_notified = True
                        continue

                    # Проверяем, связана ли транзакция с нашим кошельком
                    accounts = data.get("value", {}).get("transaction", {}).get("message", {}).get("accountKeys", [])
                    if address not in accounts:
                        continue

                    signature = data.get("value", {}).get("signature")
                    if not signature:
                        continue

                    logger.info(f"Новая транзакция для {name} через программу {program_id}: {signature}")

                    # Используем Solana JSON-RPC для получения деталей транзакции
                    tx_response = solana_client.get_transaction(signature, encoding="jsonParsed")
                    if not tx_response["result"]:
                        if not error_notified:
                            bot.send_message(chat_id=chat_id, text=f"Не удалось получить детали транзакции {signature} для кошелька {name}.")
                            error_notified = True
                        continue

                    tx = tx_response["result"]
                    tx_type = classify_transaction(tx)
                    if tx_type in types:
                        # Упрощенные данные о транзакции (нужен API для точных данных)
                        sol_amount = tx.get("meta", {}).get("fee", 0) / 1_000_000_000  # Лампорты в SOL (используем fee как пример)
                        usd_amount = sol_amount * SOL_TO_USD
                        token_amount = random.uniform(5000000, 10000000)  # Пример
                        token_name = "NYCPR"  # Нужно получать через API
                        token_price = 0.000037  # Пример
                        market_cap = "300.4K"  # Пример

                        msg = (
                            f"#{name.upper()}\n"
                            f"Swapped {sol_amount:.2f} #SOL (${usd_amount:,.2f}) for {token_amount:,.2f} #{token_name} @ ${token_price}\n"
                            f"MC: ${market_cap}\n"
                            f"#Solana | [ViewTx](https://solscan.io/tx/{signature}) | [Chart](https://www.dextools.io/app/en/solana)\n"
                            f"👉 Купить можно тут: https://gmgn.ai/?ref=HiDMfJX4&chain=sol\n"
                            f"👉 Купить через Bloom: https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J"
                        )
                        bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                        logger.info(f"Уведомление отправлено для {name}: {tx_type}")
                except Exception as e:
                    logger.error(f"Ошибка обработки транзакции для {name} (программа {program_id}): {str(e)}")
                    if not error_notified:
                        bot.send_message(chat_id=chat_id, text=f"Ошибка мониторинга {name} (программа {program_id}): {str(e)}")
                        error_notified = True
        finally:
            # Отписываемся при завершении
            await ws.program_unsubscribe(subscription_id)

# Подписка на изменения аккаунта (для прямых операций с SOL)
async def monitor_account_ws(address, name, types, chat_id):
    async with connect(SOLANA_WS_URL) as ws:
        # Даём задержку для инициализации WebSocket
        await asyncio.sleep(5)

        # Подписываемся на изменения аккаунта
        await ws.account_subscribe(address)
        first_resp = await ws.recv()
        subscription_id = first_resp.result
        logger.info(f"Подписка на изменения аккаунта {name} ({address}) успешна, ID подписки: {subscription_id}")

        error_notified = False  # Флаг для отслеживания ошибок
        try:
            async for msg in ws:
                # Парсим сообщение от WebSocket
                try:
                    data = msg.result
                    if not data:
                        if not error_notified:
                            bot.send_message(chat_id=chat_id, text=f"Кошелек {name} ({address}) неактивен или не имеет транзакций.")
                            error_notified = True
                        continue

                    # Получаем подпись транзакции
                    signature = data.get("value", {}).get("signature")
                    if not signature:
                        continue

                    logger.info(f"Новая транзакция для {name} (account_subscribe): {signature}")

                    # Используем Solana JSON-RPC для получения деталей транзакции
                    tx_response = solana_client.get_transaction(signature, encoding="jsonParsed")
                    if not tx_response["result"]:
                        if not error_notified:
                            bot.send_message(chat_id=chat_id, text=f"Не удалось получить детали транзакции {signature} для кошелька {name}.")
                            error_notified = True
                        continue

                    tx = tx_response["result"]
                    tx_type = classify_transaction(tx)
                    if tx_type in types:
                        # Упрощенные данные о транзакции (нужен API для точных данных)
                        sol_amount = tx.get("meta", {}).get("fee", 0) / 1_000_000_000  # Лампорты в SOL (используем fee как пример)
                        usd_amount = sol_amount * SOL_TO_USD
                        token_amount = random.uniform(5000000, 10000000)  # Пример
                        token_name = "NYCPR"  # Нужно получать через API
                        token_price = 0.000037  # Пример
                        market_cap = "300.4K"  # Пример

                        msg = (
                            f"#{name.upper()}\n"
                            f"Swapped {sol_amount:.2f} #SOL (${usd_amount:,.2f}) for {token_amount:,.2f} #{token_name} @ ${token_price}\n"
                            f"MC: ${market_cap}\n"
                            f"#Solana | [ViewTx](https://solscan.io/tx/{signature}) | [Chart](https://www.dextools.io/app/en/solana)\n"
                            f"👉 Купить можно тут: https://gmgn.ai/?ref=HiDMfJX4&chain=sol\n"
                            f"👉 Купить через Bloom: https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J"
                        )
                        bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                        logger.info(f"Уведомление отправлено для {name}: {tx_type}")
                except Exception as e:
                    logger.error(f"Ошибка обработки транзакции для {name} (account_subscribe): {str(e)}")
                    if not error_notified:
                        bot.send_message(chat_id=chat_id, text=f"Ошибка мониторинга {name} (account_subscribe): {str(e)}")
                        error_notified = True
        finally:
            # Отписываемся при завершении
            await ws.account_unsubscribe(subscription_id)

# Мониторинг кошелька через все программы
def monitor_wallet(address, name, types, chat_id):
    # Запускаем мониторинг для SPL Token Program
    spl_thread = Thread(target=lambda: updater.run_async(monitor_program_ws, address, name, types, chat_id, SPL_TOKEN_PROGRAM_ID))
    spl_thread.start()

    # Запускаем мониторинг для Jupiter Aggregator
    jupiter_thread = Thread(target=lambda: updater.run_async(monitor_program_ws, address, name, types, chat_id, JUPITER_PROGRAM_ID))
    jupiter_thread.start()

    # Запускаем мониторинг для Pump Fun
    pump_fun_thread = Thread(target=lambda: updater.run_async(monitor_program_ws, address, name, types, chat_id, PUMP_FUN_PROGRAM_ID))
    pump_fun_thread.start()

    # Запускаем мониторинг для Raydium
    raydium_thread = Thread(target=lambda: updater.run_async(monitor_program_ws, address, name, types, chat_id, RAYDIUM_PROGRAM_ID))
    raydium_thread.start()

    # Запускаем мониторинг изменений аккаунта (для прямых операций с SOL)
    account_thread = Thread(target=lambda: updater.run_async(monitor_account_ws, address, name, types, chat_id))
    account_thread.start()

    # Сохраняем все потоки
    with wallet_lock:
        monitoring_threads[(name, "spl")] = spl_thread
        monitoring_threads[(name, "jupiter")] = jupiter_thread
        monitoring_threads[(name, "pump_fun")] = pump_fun_thread
        monitoring_threads[(name, "raydium")] = raydium_thread
        monitoring_threads[(name, "account")] = account_thread

# Классификация транзакций
def classify_transaction(tx):
    meta = tx.get("meta", {})
    instructions = tx.get("transaction", {}).get("message", {}).get("instructions", [])
    
    # Проверяем тип транзакции
    for instruction in instructions:
        program_id = instruction.get("programId", "")
        if "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623DQ5x" in program_id:
            # SPL Token Program
            parsed = instruction.get("parsed", {})
            if parsed and parsed.get("type") == "transfer":
                return "transfer"
            elif parsed and parsed.get("type") == "mint":
                return "nft_mint"
        elif "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTp1" in program_id:
            # Jupiter Aggregator (свапы)
            return "swap"
        elif "6EF8rrecthR5DkcocFusWxY6dvdTQXThK6JVZSJ1C1" in program_id:
            # Pump Fun (свапы или покупка/продажа токенов)
            return "swap"
        elif "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8" in program_id:
            # Raydium (свапы)
            return "swap"
    
    # Проверяем изменения баланса SOL
    if meta.get("preBalances") and meta.get("postBalances"):
        pre_balances = meta["preBalances"]
        post_balances = meta["postBalances"]
        if pre_balances[0] != post_balances[0]:
            return "receive" if post_balances[0] > pre_balances[0] else "send"
    
    return "unknown"

# Главное меню с кнопками
def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ Add", callback_data='add')],
        [InlineKeyboardButton("📁 List", callback_data='list')],
        [InlineKeyboardButton("✅ Menu", callback_data='menu')]
    ]
    return InlineKeyboardMarkup(keyboard)

# Меню типов транзакций
def types_menu(selected_types):
    types = [
        ("Swap", "swap"), ("Swap Buy", "swap_buy"), ("Swap Sell", "swap_sell"),
        ("Transfer", "transfer"), ("Lending", "lending"),
        ("NFT Mint", "nft_mint"), ("NFT Trade", "nft_trade"),
        ("NFT Transfer", "nft_transfer"), ("NFT Lending", "nft_lending"),
        ("Bridge", "bridge"), ("Reward", "reward"),
        ("Approvals", "approvals"), ("Perpetual", "perpetual"),
        ("Option", "option"), ("Wrap", "wrap"),
        ("NFT liquidation", "nft_liquidation"), ("Contract creation", "contract_creation"),
        ("Other", "other")
    ]
    keyboard = []
    row = []
    for label, type_id in types:
        emoji = "✅" if type_id in selected_types else "⬜"
        row.append(InlineKeyboardButton(f"{emoji} {label}", callback_data=f"type_{type_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        InlineKeyboardButton("Select All", callback_data='select_all'),
        InlineKeyboardButton("✅ Confirm", callback_data='confirm_types'),
        InlineKeyboardButton("❌ Cancel", callback_data='cancel')
    ])
    return InlineKeyboardMarkup(keyboard)

# Команда /start
def start(update, context):
    update.message.reply_text(
        "Привет! Я трекер кошельков.\nВыбери действие:",
        reply_markup=main_menu()
    )
    logger.info("Команда /start выполнена")

# Обработчик нажатий на кнопки
def button(update, context):
    query = update.callback_query
    query.answer()
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    data = query.data

    if data == 'add':
        user_states[user_id] = {'state': 'awaiting_address', 'selected_types': []}
        query.message.reply_text("Введите адрес кошелька Solana:")
    elif data == 'list':
        with wallet_lock:
            if not tracked_wallets:
                query.message.reply_text("Нет отслеживаемых кошельков.", reply_markup=main_menu())
                return
            response = "Список отслеживаемых кошельков:\n\n"
            for name, data in tracked_wallets.items():
                response += f"💼 {name} (Solana)\nКОПИРОВАТЬ\n{data['address']}\n/edit_{random.randint(1000000, 9999999)}\n\n"
        query.message.reply_text(response, reply_markup=main_menu())
        logger.info("Список кошельков отправлен")
    elif data == 'menu':
        keyboard = [
            [InlineKeyboardButton("➕ Add", callback_data='add')],
            [InlineKeyboardButton("📁 List", callback_data='list')],
            [InlineKeyboardButton("📢 Канал @degen_danny", url='https://t.me/degen_danny')]
        ]
        query.message.reply_text(
            "Меню:\n"
            "Канал: @degen_danny\n"
            "Выбери действие:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif data == 'cancel':
        if user_id in user_states:
            del user_states[user_id]
        query.message.reply_text("Действие отменено.", reply_markup=main_menu())
    elif data.startswith('type_'):
        type_id = data.split('_')[1]
        if user_id not in user_states:
            return
        selected_types = user_states[user_id].get('selected_types', [])
        if type_id in selected_types:
            selected_types.remove(type_id)
        else:
            selected_types.append(type_id)
        user_states[user_id]['selected_types'] = selected_types
        query.message.edit_reply_markup(reply_markup=types_menu(selected_types))
    elif data == 'select_all':
        if user_id not in user_states:
            return
        # Выбираем все типы транзакций
        all_types = [
            "swap", "swap_buy", "swap_sell", "transfer", "lending",
            "nft_mint", "nft_trade", "nft_transfer", "nft_lending",
            "bridge", "reward", "approvals", "perpetual", "option",
            "wrap", "nft_liquidation", "contract_creation", "other"
        ]
        user_states[user_id]['selected_types'] = all_types
        query.message.edit_reply_markup(reply_markup=types_menu(all_types))
    elif data == 'confirm_types':
        if user_id not in user_states:
            return
        state = user_states[user_id]
        name = state.get('name')
        address = state.get('address')
        types = state.get('selected_types', [])
        if not types:
            query.message.reply_text("Выберите хотя бы один тип транзакции.", reply_markup=types_menu(types))
            return
        
        with wallet_lock:
            tracked_wallets[name] = {"address": address, "types": types, "last_tx": None}
        # Запускаем мониторинг через все программы
        monitor_wallet(address, name, types, chat_id)
        query.message.reply_text(f"Кошелек {name} добавлен в отслеживание.", reply_markup=main_menu())
        logger.info(f"Кошелек {name} добавлен: {address}, типы: {types}")
        del user_states[user_id]

# Обработчик текстовых сообщений
def handle_message(update, context):
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    text = update.message.text

    if user_id not in user_states:
        update.message.reply_text("Пожалуйста, используйте кнопки для взаимодействия.", reply_markup=main_menu())
        return

    state = user_states[user_id]['state']

    if state == 'awaiting_address':
        user_states[user_id]['address'] = text
        user_states[user_id]['state'] = 'awaiting_name'
        update.message.reply_text("Введите название кошелька:")
    elif state == 'awaiting_name':
        name = text
        user_states[user_id]['name'] = name
        user_states[user_id]['state'] = 'awaiting_types'
        update.message.reply_text("Выберите типы транзакций для отслеживания:", reply_markup=types_menu([]))

def main():
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
