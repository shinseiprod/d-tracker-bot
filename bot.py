import telegram
from telegram.ext import Updater, CommandHandler
import requests
import time
from threading import Thread
import logging
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Твой Telegram Bot токен из переменной окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в переменных окружения!")

# Словарь для хранения кошельков
tracked_wallets = {}

# Telegram бот
updater = Updater(BOT_TOKEN, use_context=True)
bot = updater.bot

def monitor_wallet(address, name, types, chat_id):
    last_tx = None
    while name in tracked_wallets:
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
                    if tx_type in types:
                        msg = (
                            f"Кошелек: {name} ({address})\n"
                            f"Тип: {tx_type}\n"
                            f"Хэш: {tx_hash}\n"
                            f"Время: {time.ctime(tx['blockTime'])}"
                        )
                        bot.send_message(chat_id=chat_id, text=msg)
                        logger.info(f"Уведомление отправлено для {name}: {tx_type}")
            else:
                logger.warning(f"Нет транзакций для {address}")
        except Exception as e:
            logger.error(f"Ошибка мониторинга {name}: {str(e)}")
            bot.send_message(chat_id=chat_id, text=f"Ошибка мониторинга {name}: {str(e)}")
        time.sleep(5)

def classify_transaction(tx):
    changes = tx.get("change", [])
    if not changes:
        return "unknown"
    
    amount_change = changes[0]["amount"]
    token = changes[0].get("tokenAddress", "")
    
    if tx["lamport"] != 0:
        return "receive" if tx["lamport"] > 0 else "send"
    elif token:
        return "buy" if amount_change > 0 else "sell"
    elif "swap" in tx.get("txType", "").lower():
        return "swap"
    return "unknown"

def add_wallet(update, context):
    try:
        address, name = context.args
        if name in tracked_wallets:
            update.message.reply_text(f"Кошелек с именем {name} уже отслеживается.")
            return
        tracked_wallets[name] = {"address": address, "types": [], "last_tx": None}
        update.message.reply_text(f"Добавлен кошелек: {name} ({address}). Укажи типы через /track.")
        logger.info(f"Добавлен кошелек: {name} ({address})")
    except ValueError:
        update.message.reply_text("Используй: /add <address> <name>")
        logger.error("Ошибка команды /add: неверный формат")

def track_wallet(update, context):
    try:
        name, types_str = context.args[0], ",".join(context.args[1:])
        if name not in tracked_wallets:
            update.message.reply_text(f"Кошелек {name} не найден. Добавь через /add.")
            return
        types = types_str.split(",")
        valid_types = {"swap", "buy", "sell", "send", "receive"}
        if not all(t in valid_types for t in types):
            update.message.reply_text(f"Доступные типы: {', '.join(valid_types)}")
            return
        
        tracked_wallets[name]["types"] = types
        chat_id = update.message.chat_id
        
        thread = Thread(target=monitor_wallet, args=(tracked_wallets[name]["address"], name, types, chat_id))
        thread.start()
        
        update.message.reply_text(f"Отслеживание начато для {name}: {types_str}")
        logger.info(f"Отслеживание начато для {name}: {types_str}")
    except Exception as e:
        update.message.reply_text(f"Ошибка: {str(e)}. Используй: /track <name> <types>")
        logger.error(f"Ошибка команды /track: {str(e)}")

def list_wallets(update, context):
    if not tracked_wallets:
        update.message.reply_text("Нет отслеживаемых кошельков.")
        return
    response = "Отслеживаемые кошельки:\n"
    for name, data in tracked_wallets.items():
        response += f"{name}: {data['address']} (Типы: {', '.join(data['types'])})\n"
    update.message.reply_text(response)
    logger.info("Список кошельков отправлен")

def remove_wallet(update, context):
    try:
        name = context.args[0]
        if name in tracked_wallets:
            del tracked_wallets[name]
            update.message.reply_text(f"Кошелек {name} удален.")
            logger.info(f"Кошелек {name} удален")
        else:
            update.message.reply_text(f"Кошелек {name} не найден.")
    except IndexError:
        update.message.reply_text("Используй: /remove <name>")
        logger.error("Ошибка команды /remove: неверный формат")

def start(update, context):
    update.message.reply_text(
        "Привет! Я трекер кошельков.\n"
        "Команды:\n"
        "/add <address> <name> — добавить кошелек\n"
        "/track <name> <types> — отслеживать типы (swap,buy,sell,send,receive)\n"
        "/list — список кошельков\n"
        "/remove <name> — удалить кошелек"
    )
    logger.info("Команда /start выполнена")

def main():
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("add", add_wallet))
    dp.add_handler(CommandHandler("track", track_wallet))
    dp.add_handler(CommandHandler("list", list_wallets))
    dp.add_handler(CommandHandler("remove", remove_wallet))
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
