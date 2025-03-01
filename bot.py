import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import requests
import time
from threading import Thread, Lock
import logging
import os
import random

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Твой Telegram Bot токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения!")

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

# Проверка существования кошелька
def check_wallet(address):
    try:
        url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=1"
        response = requests.get(url)
        response.raise_for_status()
        return True
    except requests.exceptions.HTTPError as e:
        if response.status_code == 404:
            return False
        raise e
    except Exception as e:
        logger.error(f"Ошибка проверки кошелька {address}: {str(e)}")
        return False

# Мониторинг кошелька
def monitor_wallet(address, name, types, chat_id):
    last_tx = None
    error_notified = False  # Флаг для отслеживания, было ли уже отправлено сообщение об ошибке
    while True:
        # Проверяем, находится ли кошелек в списке отслеживания
        with wallet_lock:
            if name not in tracked_wallets:
                logger.info(f"Мониторинг кошелька {name} остановлен: кошелек удален из отслеживания")
                break

        try:
            url = f"https://public-api.solscan.io/account/transactions?account={address}&limit=1"
            response = requests.get(url)
            response.raise_for_status()
            txs = response.json()
            
            if txs and len(txs) > 0:
                tx = txs[0]
                tx_hash = tx["txHash"]
                if tx_hash != last_tx:
                    last_tx = tx_hash
                    tx_type = classify_transaction(tx)
                    logger.info(f"Обнаружена транзакция для {name}: {tx_type}, хэш: {tx_hash}")
                    if tx_type in types:
                        # Упрощенные данные о свапе (нужен API для точных данных)
                        sol_amount = tx.get("lamport", 0) / 1_000_000_000  # Лампорты в SOL
                        usd_amount = sol_amount * SOL_TO_USD
                        token_amount = random.uniform(5000000, 10000000)  # Пример
                        token_name = "NYCPR"  # Нужно получать через API
                        token_price = 0.000037  # Пример
                        market_cap = "300.4K"  # Пример

                        msg = (
                            f"#{name.upper()}\n"
                            f"Swapped {sol_amount:.2f} #SOL (${usd_amount:,.2f}) for {token_amount:,.2f} #{token_name} @ ${token_price}\n"
                            f"MC: ${market_cap}\n"
                            f"#Solana | [Cielo](https://www.cielo.app/) | [ViewTx](https://solscan.io/tx/{tx_hash}) | [Chart](https://www.dextools.io/app/en/solana)\n"
                            f"[Buy on Trojan](https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J)\n\n"
                            f"👉 Купить можно тут: https://gmgn.ai/?ref=HiDMfJX4&chain=sol\n"
                            f"👉 Купить через Bloom: https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J"
                        )
                        bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                        logger.info(f"Уведомление отправлено для {name}: {tx_type}")
            else:
                logger.warning(f"Нет транзакций для {address}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404 and not error_notified:
                logger.error(f"Кошелек {name} ({address}) не найден на Solscan")
                bot.send_message(chat_id=chat_id, text=f"Кошелек {name} ({address}) не найден на Solscan. Возможно, он неактивен или введен неверно.")
                error_notified = True  # Устанавливаем флаг, чтобы не повторять сообщение
                # НЕ удаляем кошелек, продолжаем мониторинг
            else:
                logger.error(f"Ошибка мониторинга {name}: {str(e)}")
                bot.send_message(chat_id=chat_id, text=f"Ошибка мониторинга {name}: {str(e)}")
        except Exception as e:
            logger.error(f"Ошибка мониторинга {name}: {str(e)}")
            bot.send_message(chat_id=chat_id, text=f"Ошибка мониторинга {name}: {str(e)}")
        time.sleep(5)

# Классификация транзакций
def classify_transaction(tx):
    changes = tx.get("change", [])
    if not changes:
        return "unknown"
    
    amount_change = changes[0]["amount"]
    token = changes[0].get("tokenAddress", "")
    
    # Более точная классификация свапов
    if "swap" in tx.get("txType", "").lower() or "Swap" in str(tx):
        return "swap"
    elif tx["lamport"] != 0:
        return "receive" if tx["lamport"] > 0 else "send"
    elif token:
        return "buy" if amount_change > 0 else "sell"
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
        
        # Проверяем кошелек перед мониторингом
        if not check_wallet(address):
            query.message.reply_text(
                f"Кошелек {address} не найден на Solscan. Проверьте адрес и попробуйте снова.",
                reply_markup=main_menu()
            )
            del user_states[user_id]
            return

        with wallet_lock:
            tracked_wallets[name] = {"address": address, "types": types, "last_tx": None}
        thread = Thread(target=monitor_wallet, args=(address, name, types, chat_id))
        thread.start()
        with wallet_lock:
            monitoring_threads[name] = thread  # Сохраняем поток
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
