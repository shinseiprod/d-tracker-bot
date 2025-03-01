import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters
import requests
import time
from threading import Thread
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

# Словарь для хранения кошельков
tracked_wallets = {}

# Временное хранилище для состояния
user_states = {}

# Telegram бот
updater = Updater(BOT_TOKEN, use_context=True)
bot = updater.bot

# Курс SOL в USD (для теста, нужно получать через API, например, CoinGecko)
SOL_TO_USD = 137.0  # Пример: 1 SOL = 137 USD (как на скриншоте)

# Мониторинг кошелька
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
                        # Упрощенные данные о свапе (нужен API для точных данных)
                        sol_amount = tx.get("lamport", 0) / 1_000_000_000  # Лампорты в SOL
                        usd_amount = sol_amount * SOL_TO_USD
                        token_amount = random.uniform(5000000, 10000000)  # Пример, нужно получать через API
                        token_name = "NYCPR"  # Нужно получать через API
                        token_price = 0.000037  # Пример
                        market_cap = "300.4K"  # Пример, нужно получать через API

                        msg = (
                            f"#{name.upper()}\n"
                            f"Swapped {sol_amount:.2f} #SOL (${usd_amount:,.2f}) for {token_amount:,.2f} #{token_name} @ ${token_price}\n"
                            f"MC: ${market_cap}\n"
                            f"#Solana | [Cielo](https://www.cielo.app/) | [ViewTx](https://solscan.io/tx/{tx_hash}) | [Chart](https://www.dextools.io/app/en/solana)\n"
                            f"[Buy on Trojan](https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J)\n\n"
                            f"Купить можно тут: https://gmgn.ai/?ref=HiDMfJX4&chain=sol\n"
                            f"Купить через Bloom: https://t.me/BloomSolana_bot?start=ref_57Z29YIQ2J"
                        )
                        bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
                        logger.info(f"Уведомление отправлено для {name}: {tx_type}")
            else:
                logger.warning(f"Нет транзакций для {address}")
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
    
    if "swap" in tx.get("txType", "").lower():
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
        InlineKeyboardButton("✅ Confirm", callback
