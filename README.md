# Store Bot

A Telegram digital-product store: browse a catalog, pay from a wallet, get
delivery in the chat. Wallet top-ups go through NOWPayments, Cryptomus or
Binance Pay; gift codes and admin credits also fund wallets. Sales, deposits
and low stock are announced in a channel.

Everything is configured with environment variables — no tokens, keys, ids or
links are in the code. A fresh clone with only `BOT_TOKEN` and `ADMIN_IDS`
set is fully browsable.

## Run it on your own machine

```bash
pip install -r requirements.txt
cp .env.example .env     # fill in BOT_TOKEN and ADMIN_IDS at minimum
python bot.py
```

`.env` is read at startup, so that is the whole setup. A real environment
variable still wins, which keeps `BOT_TOKEN=... python bot.py` and cloud
dashboards working unchanged.

Or just run **`start.bat`** (Windows, double-clickable) / **`./start.sh`**
(macOS, Linux, Git Bash). They install dependencies, check `.env` exists, and
restart the bot if it crashes — Ctrl+C stops it for good.

Send `/id` to the bot to learn your numeric id, put it in `ADMIN_IDS`,
restart, then `/admin` opens the panel.

**A localhost bot is a real bot.** The bot long-polls Telegram, so it needs no
public URL, no port forwarding and no tunnel — it works behind any router.
Two consequences of running at home: it is only online while the process is
(use Task Scheduler / `launchd` / a systemd unit for always-on), and
`data/` lives on this disk, so back that folder up — it holds your users,
orders, balances and codes.

`HTTP_HOST=127.0.0.1` in `.env` keeps the built-in HTTP server reachable from
this machine only. Cloud hosts need `0.0.0.0`, which is the default.

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
| Wallet — balance, Customer ID, recent activity | Wallet button, `/wallet` |
| Add funds — pick method, then amount | Wallet → Top up, `/topup` |
| Orders and order detail with resend | Orders button, `/orders` |
| Gift code redemption | Gift code button, `/gift CODE` |
| Support, Profile, Language, Help, Terms | the remaining buttons |

Quantity, coupons, volume discounts, per-product alerts (Stop Alerts / Get
Alerts) and the delivery note all live on the product screen.

### Volume discounts

Give a product bulk tiers (**/admin → product → Bulk rates**), one per line:

```
5 | 0.15
10 | 0.20
```

Buy 5+ and every unit costs 0.15 less; 10+ and it is 0.20 less (highest
matching tier wins). The tiers show on the product screen, the category
listing (`Bulk x5+`), the confirm screen (as a saving) and in stock-alert
posts — and each threshold becomes a one-tap quantity button.

### Wallet transfers

Every customer gets a stable, shareable **Customer ID** (`#CX-201566`) that
reveals nothing about their Telegram account. Wallet → Transfer sends balance
to another customer by that ID, and both sides get a confirmation.

### Animated emoji on buttons

Buttons put their emoji in `icon_custom_emoji_id` and keep a bare text
label, so the animated icon sits in the button chrome.

This needs the **same privilege as custom emoji in message text** — a
Fragment username, or a Premium-owned bot. Without it the field is accepted
and silently ignored, leaving a button with *no* emoji at all, which is worse
than not using it. `BUTTON_ICONS` defaults on; set it to `0` to force the
label-prefix fallback, which works on any bot.

### Picking emoji that actually look right

An id's `emoji` field says which character it stands for, but **nothing
guarantees the artwork matches**. Themed packs are the trap: a gifts pack
registers gift-box art under assorted characters, and a logo pack served the
Reddit mark for 👤. Metadata alone will not catch this.

`app/handlers/admin.py` therefore prefers icon-style packs (`UI_Icons`,
`OutlineEmoji`, `FinanceEmoji`, `NewsEmoji`) over themed ones. When a slot
still looks wrong, download the sticker's thumbnail via `getFile` and look at
it — that is the only reliable check. A slot with no good artwork is better
left unmapped: the plain system glyph is clean and correct.

### Coloured buttons

Buttons carry a `style` field. Verified against the live API — Telegram
*validates* it on reply-keyboard buttons and rejects anything else, so the
accepted set is exactly:

| `style` | Inline button | Reply keyboard |
|---|---|---|
| `primary` | teal | **blue** |
| `success` | green | green |
| `danger` | red | red |
| `default` (or omitted) | dark | dark |

The persistent menu uses `primary`, so it renders blue. Confirm actions are
green and destructive ones red. Turn the whole thing off with
`BUTTON_STYLES=0`.

### Posters (off)

The storefront is text-only. `POSTERS` defaults to `0`, and while it is off
`store.poster()` returns nothing — no stored `file_id`, env var or product
image can put an image back, which is asserted in `tests/smoke.py`.

To turn images back on, set `POSTERS=1` and give the slots something: the
`BANNER_*` / `POSTER_*` env vars take an `https://` URL, a Telegram
`file_id`, or a path to a file in the repo, and a product's `image` field
overrides `BANNER_PRODUCTS` for its own screen.

Note a `file_id` belongs to the bot that uploaded it, so images do not
survive a change of bot token — you would get
`Bad Request: wrong file identifier` and the screen silently falls back to
text.

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

## Payments

Three gateways ship built in. Each button only appears once its own
credentials are set; until then the payment screen says no method is enabled
and points at gift codes and support.

All are **polled, not webhooked** — the bot asks the gateway whether a payment
landed when the customer presses *I have paid*. That is why the bot runs fine
on localhost: it needs no public URL, no port forward and no tunnel.

### NOWPayments — `NOWPAYMENTS_API_KEY`

Non-custodial: funds forward to the outcome wallet you set in their dashboard
rather than sitting in an account balance. No KYC and no domain verification,
and auth is a single header with no request signing.

Unlike the other two there is no checkout page — the bot shows the deposit
address and exact amount in the chat, so the customer never leaves Telegram.

Customers pay in one coin, `NOWPAYMENTS_PAY_CURRENCY`. Check the key and,
more importantly, the minimum:

```
python -m tools.check_nowpayments
```

**Set the pay currency to match your outcome wallet.** The minimum depends on
the *pair*, not the coin, and getting it wrong is brutal. Measured against a
BEP-20 USDT outcome wallet:

| Customer pays | Minimum |
|---|---|
| `usdtbsc` — matches the wallet | **~$0.09** |
| `ton` | ~$0.14 |
| `usdtmatic` | ~$0.24 |
| `btc` | ~$0.99 |
| `usdterc20` | ~$1.12 |
| `usdttrc20` | **~$11.95** |

A mismatch forces a conversion, which raises the floor by up to 100x and
moves you from the 1% fee to 1.5%. For a store selling items at a dollar or
two, that floor — not the fee — decides whether the gateway works at all.

The tool prints your real floor in both the coin and your own currency, ranks
every candidate coin, and compares the result against `MIN_TOPUP` and your
cheapest product.

This flow uses `POST /v1/payment`, not `/v1/invoice`, for a specific reason:
an invoice gives a hosted page, but the payment it spawns can only be found
again through `GET /v1/payment/` — which needs JWT auth (email + password).
`GET /v1/payment/{id}` accepts the API key, and `POST /v1/payment` returns
that id up front, so the whole flow works with the key alone.

### Cryptomus — `CRYPTOMUS_MERCHANT_ID` + `CRYPTOMUS_API_KEY`

Accepts payment from any wallet, so it reaches customers who do not hold an
account with any particular exchange. Use the **payment** API key; payouts use
a separate key that this bot never needs.

`CRYPTOMUS_SUBTRACT=100` (the default) charges Cryptomus' commission to the
buyer, so the full invoice amount reaches your balance.

To see the commission and per-coin minimums your account actually gets:

```
python -m tools.check_cryptomus
```

Worth running before you go live — some coins have a minimum well above
`MIN_TOPUP`, and the public tariffs page does not render its own fee tables.

Cryptomus has no cancel-invoice API, so `CRYPTOMUS_LIFETIME` (default:
`ORDER_EXPIRY_MINUTES`) is what retires an abandoned invoice. Reusing an
`order_id` returns the existing invoice rather than creating a second one, so
a double-tapped Pay button cannot produce two invoices.

### Binance Pay — `BINANCE_PAY_KEY` + `BINANCE_PAY_SECRET`

Needs an approved merchant account, which is the slower path to get started.

### Manual

`MANUAL_PAY=1` adds a "pay by hand" method: the customer presses *I have
paid*, admins get an Approve/Decline message, and approving credits the
wallet. Worth leaving on as a fallback.

### Adding a fourth

One `Method` entry in `app/payments.py` plus a create/check pair, wired into
`available()` and the dispatch in `create_invoice` / `check_invoice`. Nothing
else in the bot changes — both method screens lay their buttons out from
whatever `available()` returns.

If the gateway gives an address instead of a checkout page, return
`instructions` from `create_invoice` as `label|value` lines; the invoice
screen renders each value as a tap-to-copy code span.

A gateway must never credit a wallet on an error it cannot interpret:
`check_invoice` returns `PENDING` for anything it does not positively
recognise as paid or failed.

## Languages

English, Bengali, Hindi, Russian, Chinese and Vietnamese. Buttons, titles and
all short UI lines are translated; a few long blocks (the default terms text,
some help copy) fall back to English. Missing strings always fall back to
English rather than failing, so you can add a language incrementally in
`app/lang.py`.

## Premium (animated) emoji

> **Your bot probably cannot send these.** Per the Bot API: *"Custom emoji
> entities can only be used by bots that purchased additional usernames on
> Fragment or in the messages directly sent by the bot to private, group and
> supergroup chats if the owner of the bot has a Telegram Premium
> subscription."*
>
> A bot without that privilege gets **no error**. Telegram accepts the
> message and silently removes the entities, so every emoji arrives as plain
> unicode and the only symptom is "my emoji don't animate". This bot detects
> it — the first message containing custom emoji compares what came back, logs
> a warning, and **/admin → Emoji** says so plainly.
>
> `python -m tools.switch_bot <token>` tests any token for this before you
> commit to it, and `--write` then updates `.env`.
>
> **Moving to a new bot? Re-upload the posters.** A Telegram `file_id`
> belongs to the bot that uploaded it, so every stored poster breaks with a
> new token (`Bad Request: wrong file identifier`). The screens degrade to
> text rather than failing, but regenerate them: **/admin → product → Make
> poster** per product, or re-run your banner install. Everything else in
> `data/` — catalog, users, orders, balances, codes — carries over untouched,
> and emoji ids are global so `data/emoji.json` needs nothing.
>
> Two ways to unlock it, neither of them code:
> 1. Give the **owner account** (whichever account created the bot in
>    @BotFather) Telegram Premium — the recipient's Premium status is
>    irrelevant.
> 2. Buy an additional username for the bot on Fragment.
>
> Until then the plain unicode fallback is what customers see, and it looks
> fine — it is what every non-Premium-owned store bot shows.


The UI uses named emoji slots, each with a plain unicode fallback. Map a slot
to a premium custom emoji and it animates for Premium users; everyone else
sees the same plain character.

**The easy way — forward one message.** As an admin, forward any message that
uses premium emoji into the bot. It reads the `custom_emoji_id`s out of the
entities, then pulls *every emoji in the sets those stickers belong to* — one
message typically yields several hundred emoji, enough to fill almost every
slot at once. Slots are matched by the emoji each sticker represents, so the
animated version and the plain fallback always show the same picture. The bot
replies with how many slots are live and which are still plain.

**The manual way.** Write `data/emoji.json` yourself:

```json
{ "products": "5355193051193059834", "wallet": "5447453226498552490" }
```

Slot names are the keys of `EMOJI` in `app/emoji.py`.

**/admin → Emoji** reports how many slots are mapped, how many ids are
animated vs static, which sets they come from, and prints a live sample line.
Use it to tell "not installed" apart from "installed but my client isn't
animating them".

Two safety nets matter here. A bad id can never make a message fail to send —
the send is retried without custom-emoji entities. And because Telegram
rejects a whole message if *any* id in it is invalid (which would silently
strip every emoji in the bot), startup audits the map against
`getCustomEmojiStickers` and drops dead ids before they can do that.

## Tests

No network, no token needed:

```bash
python -m tests.smoke   # renders every screen in every language
python -m tests.flow    # drives updates through the router with a faked API
python -m tests.gateway # gateway signing, statuses and failure handling
```

Both suites refuse to run against a real `DATA_DIR` — they buy products,
credit wallets and ban users, so pointing them at live data would corrupt it.
Unset `DATA_DIR` (they use a temp dir) or pass `ALLOW_LIVE_DATA=1` knowingly.

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
app/payments.py        gateways (NOWPayments, Cryptomus, Binance Pay)
app/screens.py         customer-facing screens
app/broadcast.py       channel posts and alerts
app/shop.py            checkout and delivery
app/state.py           short-lived conversation state
app/handlers/          router, shop flow, account, admin
app/runner.py          polling loop, http server, startup
tests/                 smoke + flow + gateway
```
