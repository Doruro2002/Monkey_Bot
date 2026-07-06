"""
Run this first, by itself, to confirm your MT5 demo connection actually
works before running the full bot. On success it prints your account
balance and a sample of live price data.

    python test_connection.py
"""

import config
import data_feed


def main():
    print("Connecting to MT5...")
    ok = data_feed.connect()
    if not ok:
        print("FAILED to connect. Check MT5_LOGIN / MT5_PASSWORD / MT5_SERVER "
              "in config.py, and make sure the MT5 terminal is open and logged in.")
        return

    print("Connected successfully.\n")

    try:
        info = data_feed.get_account_info()
        print(f"Account: {info['login']}")
        print(f"Server: {info['server']}")
        print(f"Balance: {info['balance']} {info['currency']}")
        print(f"Equity: {info['equity']} {info['currency']}\n")
    except Exception as e:
        print(f"Could not fetch account info: {e}")

    for symbol in config.SYMBOLS:
        try:
            df = data_feed.get_ohlc(symbol, "M15", bars=5)
            last = df.iloc[-1]
            print(f"{symbol} M15 last close: {last['close']}  (time: {last['time']})")
        except Exception as e:
            print(f"Could not fetch {symbol} data: {e}")

    data_feed.shutdown()
    print("\nDone. If you see your balance and price data above, you're ready to run main.py.")


if __name__ == "__main__":
    main()
