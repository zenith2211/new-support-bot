# Store Bot

A Telegram digital-product store: browse a catalog, pay from a wallet, get
delivery in the chat. Wallet top-ups go through Binance Pay; gift codes and
admin credits also fund wallets. Sales, deposits and low stock are announced
in a channel.

Everything is configured with environment variables — no tokens, keys, ids or
links are in the code. A fresh clone with only `BOT_TOKEN` and `ADMIN_IDS`
set is fully browsable.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env     # fill in BOT_TOKEN and ADMIN_IDS at minimum
python bot.py
```

On Windows without a `.env` loader, set the variables in the shell first:

```bash
BOT_TOKEN=123:abc ADMIN_IDS=111222333 python bot.py
```

Send `/id` to the bot to learn your numeric id, put it in `ADMIN_IDS`,
restart, then `/admin` opens the panel.

The first run seeds a demo catalog (six categories, six products) so you can
see the storefront immediately. Delete those categories from
**/admin → Categories** once you add your own.

## What the customer sees

| Screen | How to reach it |
|---|---|
| Start — greeting, menu, full command list | `/start` |
| Categories with per-category stock counts | Products button, `/products` |
| Products in a category with price + stock | tap a category |
| Product detail — price, stock, sold, SKU, delivery, qty | tap a product |
| Confirm order — qty, total, wallet, description | tap `x1` … `x5` or Custom |
| Low balance — shortfall, min top-up | confirm without enough balance |
| Pay and get item — pick a gateway | tap Pay and get item |
| Delivered — credentials, order id | after a successful purchase |
| Wallet, top-up, history | Wallet button, `/wallet`, `/topup` |
| Orders and order detail with resend | Orders button, `/orders` |
| Gift code redemption | Gift code button, `/gift CODE` |
| Support, Profile, Language, Help, Terms | the remaining buttons |

Quantity, coupons, per-product alerts (Stop Alerts / Get Alerts) and the
delivery note all live on the product screen.

## Commands

`/start` `/products` `/wallet` `/topup` `/orders` `/gift` `/support`
`/profile` `/language` `/help` `/terms` `/id` — and `/admin` for admins.

They are declared once in `app/commands.py`, which drives the list printed
inside `/start`, Telegram's hamburger menu (registered per language), and the
router. Adding a command in one place updates all three.

## Admin panel

`/admin` gives you: categories, products, stock, gift codes, coupons, pending
top-ups, users (credit/debit, ban, direct message), broadcast, and settings.

Most actions are prompt-driven — tap a button, the bot shows the expected
syntax, you send one message:

| Action | Syntax |
|---|---|
| Add category | `Name \| emoji-slot` |
| Add product | `Name \| price \| description` |
| Add stock | one item per line (one line is delivered per unit sold) |
| New gift code | `amount \| uses \| code` (code optional) |
| New coupon | `code \| percent\|fixed \| value \| uses \| product id` |
| Credit a user | `5` or `-2.5` |

Settings editable at runtime (no redeploy): store name, support username,
channel link, min top-up, welcome note, terms text, manual-pay note, API
note, and the force-join toggle. Secrets stay in the environment.

### Stock modes

- **lines** — each stock line is delivered to one buyer, then removed.
- **unlimited** — everyone receives the product's `payload`; stock never runs out.
- **manual** — nothing is auto-delivered; support is pinged and marks the
  order delivered.

## Channel posts

Set `LOG_CHANNEL_ID` and add the bot as an admin in that channel to get:

- **WALLET FUNDED** — amount, masked customer id, method, with a *Visit bot* button
- **NEW ORDER** — product, qty, paid, masked customer id, with a *Buy now* deep link
- **ALMOST GONE** — fires once when stock drops to `LOW_STOCK_THRESHOLD`
- **BACK IN STOCK** — when you restock a sold-out product; subscribed
  customers also get a DM

Customer ids are always masked in public posts (`51******04`).

## Posters

Every `BANNER_*` / `POSTER_*` variable accepts an `https://` URL, a Telegram
`file_id`, or a path to a file in the repo. Leave one blank and that screen is
sent as plain text. Per-product posters are set in the admin panel
(**Product → Poster**) and override `BANNER_PRODUCTS`.

A screen whose text exceeds Telegram's 1024-character caption limit is sent as
text automatically, so a long description never blocks a message.

## Payments

Binance Pay is the built-in gateway. Its button only appears once both
`BINANCE_PAY_KEY` and `BINANCE_PAY_SECRET` are set; until then the payment
screen says no method is enabled and points at gift codes and support.

`MANUAL_PAY=1` adds a "pay by hand" method: the customer presses *I have
paid*, admins get an Approve/Decline message, and approving credits the
wallet.

Adding another gateway means one `Method` entry in `app/payments.py` plus a
create/check pair — nothing else in the bot changes.

## Languages

English, Bengali, Hindi, Russian, Chinese and Vietnamese. Buttons, titles and
all short UI lines are translated; a few long blocks (the default terms text,
some help copy) fall back to English. Missing strings always fall back to
English rather than failing, so you can add a language incrementally in
`app/lang.py`.

## Premium emoji (optional)

The UI uses named emoji slots. Drop a `data/emoji.json` of
`{"slot": "custom_emoji_id"}` to render animated premium emoji in those slots:

```json
{ "products": "5447387942995655277", "wallet": "5447453226498552490" }
```

Slot names are the keys of `EMOJI` in `app/emoji.py`. Unknown or rejected ids
fall back to the plain unicode character automatically — a bad id can never
make a message fail to send.

## Tests

No network, no token needed:

```bash
python -m tests.smoke   # renders every screen in every language
python -m tests.flow    # drives updates through the router with a faked API
```

`smoke` checks caption/text limits, entity offsets and `callback_data` size
for ~140 views and prints each screen so you can eyeball the layout (`-q` to
silence). `flow` covers browsing, buying, coupons, gift codes, alerts, the
admin panel and the ban gate.

## Deployment

The bot long-polls, and also serves HTTP on `PORT` so free hosting tiers stay
awake:

- `GET /` → `ok`
- `GET /health` → JSON status
- `GET /api/catalog` → read-only prices and stock, when `STORE_API_KEY` is set
  (send it as an `X-API-Key` header)

Start command: `python bot.py`.

`.github/workflows/keepalive.yml` pings the health endpoint every 10 minutes.
Set the repo variable `KEEPALIVE_URL` (Settings → Secrets and variables →
Actions → Variables) to your service's `/health` URL; the workflow no-ops
while it is unset.

**State lives in JSON files** under `DATA_DIR` (default `./data`, gitignored).
On a host with an ephemeral filesystem, point `DATA_DIR` at a mounted disk or
users, orders and balances are lost on redeploy.

## Layout

```
bot.py                 entry point
app/config.py          env settings
app/tg.py              Bot API client + view rendering
app/msg.py             entity-based message builder
app/emoji.py           named emoji slots
app/view.py            View object, buttons, keyboards
app/lang.py            every UI string, per language
app/commands.py        slash-command registry
app/store.py           JSON persistence
app/util.py            money/id/time formatting
app/payments.py        gateways (Binance Pay)
app/screens.py         customer-facing screens
app/broadcast.py       channel posts and alerts
app/shop.py            checkout and delivery
app/state.py           short-lived conversation state
app/handlers/          router, shop flow, account, admin
app/runner.py          polling loop, http server, startup
tests/                 smoke + flow
```
