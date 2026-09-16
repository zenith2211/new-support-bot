"""
Telegram digital-product store bot.

Layout:
    config.py      env-driven settings (no secrets in code)
    tg.py          Telegram Bot API client + view rendering
    msg.py         entity-based message builder
    emoji.py       named emoji slots (+ optional premium ids)
    view.py        View object and button/keyboard helpers
    lang.py        every UI string, per language
    commands.py    slash-command registry
    store.py       JSON persistence
    util.py        money/id/time formatting
    payments.py    payment gateways (Cryptomus, Binance Pay)
    screens.py     customer-facing screens
    broadcast.py   channel posts and alerts
    shop.py        checkout and delivery
    state.py       short-lived conversation state
    handlers/      routing, shop flow, account, admin
    runner.py      polling loop, http server, startup
"""

__version__ = "2.0.0"
