"""
Sends one test message to confirm your Telegram bot + chat ID are wired up
correctly, independent of whether the market is producing a real signal.

    python test_telegram.py
"""

import telegram_bot

if __name__ == "__main__":
    result = telegram_bot.send_plain_alert(
        "Test alert from your trading bot.\n\nIf you see this, Telegram is wired up correctly."
    )
    print("Result:", result)
