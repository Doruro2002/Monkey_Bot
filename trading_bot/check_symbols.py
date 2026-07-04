"""
Lists every symbol on your connected MT5 account whose name contains
XAU or GOLD, so you know the exact string to put in config.py.

    python check_symbols.py
"""

import data_feed

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def main():
    if not data_feed.connect():
        print("Could not connect to MT5 — check your env vars are set in this terminal.")
        return

    all_symbols = mt5.symbols_get()
    matches = [s.name for s in all_symbols if "XAU" in s.name.upper() or "GOLD" in s.name.upper()]

    if matches:
        print("Found these gold-related symbols on your account:")
        for m in matches:
            print(f"  - {m}")
    else:
        print("No XAU/GOLD symbols found on this account/server. "
              "This server likely doesn't offer commodities — "
              "consider a broker demo (Exness/XM/IC Markets) instead if you want Gold.")

    data_feed.shutdown()


if __name__ == "__main__":
    main()
