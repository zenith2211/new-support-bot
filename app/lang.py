"""
app/lang.py — UI strings.

Every user-facing string in the bot goes through t(). A value is either

    "key": "English text"                 -> English for every language
    "key": {"en": "...", "ru": "...", ...} -> translated, falls back to "en"

so adding a language means filling in the dicts you care about, and nothing
breaks while a translation is missing.

Placeholders use str.format: t("low_need", lang, short="1.500 USD", ...)
"""

import logging

from . import config

logger = logging.getLogger(__name__)

LANGS = {
    "en": "English",
    "bn": "বাংলা",
    "hi": "हिन्दी",
    "ru": "Русский",
    "zh": "中文",
    "vi": "Tiếng Việt",
}

LANG_FLAGS = {
    "en": "🇬🇧", "bn": "🇧🇩", "hi": "🇮🇳",
    "ru": "🇷🇺", "zh": "🇨🇳", "vi": "🇻🇳",
}

STRINGS = {
    # ─── START / MENU ─────────────────────────────────────────
    "start_hello": {
        "en": "Hello {name}",
        "bn": "হ্যালো {name}",
        "hi": "नमस्ते {name}",
        "ru": "Привет, {name}",
        "zh": "你好 {name}",
        "vi": "Xin chào {name}",
    },
    "start_tagline": {
        "en": "Digital products. Pay from wallet, then delivery is sent in "
              "this chat.",
        "bn": "ডিজিটাল প্রোডাক্ট। ওয়ালেট থেকে পেমেন্ট করুন, ডেলিভারি এই "
              "চ্যাটেই পাবেন।",
        "hi": "डिजिटल प्रोडक्ट। वॉलेट से भुगतान करें, डिलीवरी इसी चैट में "
              "मिलेगी।",
        "ru": "Цифровые товары. Оплата с кошелька, доставка приходит в этот чат.",
        "zh": "数字商品。用钱包付款，商品直接发送到本聊天。",
        "vi": "Sản phẩm số. Thanh toán bằng ví, hàng được gửi trong chat này.",
    },
    "start_tip": {
        "en": "Keep enough balance before you tap Buy.",
        "bn": "Buy চাপার আগে পর্যাপ্ত ব্যালেন্স রাখুন।",
        "hi": "Buy दबाने से पहले पर्याप्त बैलेंस रखें।",
        "ru": "Держите достаточный баланс перед нажатием Buy.",
        "zh": "点击购买前请确保余额充足。",
        "vi": "Hãy nạp đủ số dư trước khi bấm Buy.",
    },
    "start_commands": {
        "en": "Commands",
        "bn": "কমান্ড",
        "hi": "कमांड",
        "ru": "Команды",
        "zh": "命令",
        "vi": "Lệnh",
    },

    "menu_products": {
        "en": "Products", "bn": "প্রোডাক্ট", "hi": "प्रोडक्ट",
        "ru": "Товары", "zh": "商品", "vi": "Sản phẩm",
    },
    "menu_wallet": {
        "en": "Wallet", "bn": "ওয়ালেট", "hi": "वॉलेट",
        "ru": "Кошелёк", "zh": "钱包", "vi": "Ví",
    },
    "menu_orders": {
        "en": "Orders", "bn": "অর্ডার", "hi": "ऑर्डर",
        "ru": "Заказы", "zh": "订单", "vi": "Đơn hàng",
    },
    "menu_gift": {
        "en": "Gift code", "bn": "গিফট কোড", "hi": "गिफ्ट कोड",
        "ru": "Подарочный код", "zh": "礼品码", "vi": "Mã quà tặng",
    },
    "menu_support": {
        "en": "Support", "bn": "সাপোর্ট", "hi": "सपोर्ट",
        "ru": "Поддержка", "zh": "客服", "vi": "Hỗ trợ",
    },
    "menu_profile": {
        "en": "Profile", "bn": "প্রোফাইল", "hi": "प्रोफ़ाइल",
        "ru": "Профиль", "zh": "个人资料", "vi": "Trang cá nhân",
    },
    "menu_language": {
        "en": "Language", "bn": "ভাষা", "hi": "भाषा",
        "ru": "Язык", "zh": "语言", "vi": "Ngôn ngữ",
    },

    "menu_products_desc": {
        "en": "browse and buy",
        "bn": "দেখুন এবং কিনুন",
        "hi": "देखें और खरीदें",
        "ru": "смотреть и купить",
        "zh": "浏览并购买",
        "vi": "xem và mua",
    },
    "menu_orders_desc": {
        "en": "last purchases",
        "bn": "সাম্প্রতিক কেনাকাটা",
        "hi": "पिछली खरीदारी",
        "ru": "последние покупки",
        "zh": "最近的购买",
        "vi": "giao dịch gần đây",
    },
    "menu_gift_desc": {
        "en": "credit this wallet",
        "bn": "এই ওয়ালেটে ব্যালেন্স যোগ করুন",
        "hi": "इस वॉलेट में बैलेंस जोड़ें",
        "ru": "пополнить этот кошелёк",
        "zh": "为此钱包充值",
        "vi": "nạp vào ví này",
    },
    "menu_support_desc": {
        "en": "payments and missing items",
        "bn": "পেমেন্ট এবং না-পাওয়া আইটেম",
        "hi": "भुगतान और न मिले आइटम",
        "ru": "оплата и недоставленные товары",
        "zh": "付款与未收到的商品",
        "vi": "thanh toán và hàng chưa nhận",
    },

    # ─── PRODUCTS ─────────────────────────────────────────────
    "products_title": {
        "en": "Products", "bn": "প্রোডাক্ট", "hi": "प्रोडक्ट",
        "ru": "Товары", "zh": "商品", "vi": "Sản phẩm",
    },
    "products_intro": {
        "en": "Open a category to see price, stock and delivery.",
        "bn": "প্রাইস, স্টক ও ডেলিভারি দেখতে একটি ক্যাটাগরি খুলুন।",
        "hi": "कीमत, स्टॉक और डिलीवरी देखने के लिए कैटेगरी खोलें।",
        "ru": "Откройте категорию, чтобы увидеть цену, наличие и доставку.",
        "zh": "打开分类查看价格、库存和交付方式。",
        "vi": "Mở một danh mục để xem giá, tồn kho và cách giao hàng.",
    },
    "products_categories": {
        "en": "Categories", "bn": "ক্যাটাগরি", "hi": "कैटेगरी",
        "ru": "Категории", "zh": "分类", "vi": "Danh mục",
    },
    "products_tap": {
        "en": "Tap a category below.",
        "bn": "নিচে একটি ক্যাটাগরিতে চাপ দিন।",
        "hi": "नीचे किसी कैटेगरी पर टैप करें।",
        "ru": "Нажмите категорию ниже.",
        "zh": "点击下方的分类。",
        "vi": "Chạm vào một danh mục bên dưới.",
    },
    "products_empty": {
        "en": "No categories yet. Check back in a moment.",
        "bn": "এখনো কোনো ক্যাটাগরি নেই। কিছুক্ষণ পর দেখুন।",
        "hi": "अभी कोई कैटेगरी नहीं है। कुछ देर बाद देखें।",
        "ru": "Категорий пока нет. Зайдите позже.",
        "zh": "暂无分类，请稍后再看。",
        "vi": "Chưa có danh mục nào. Vui lòng xem lại sau.",
    },
    "category_intro": {
        "en": "{n} product(s) in this category. Tap a button to open price, "
              "stock and Buy.",
        "bn": "এই ক্যাটাগরিতে {n} টি প্রোডাক্ট। প্রাইস, স্টক ও Buy দেখতে "
              "বাটনে চাপ দিন।",
        "hi": "इस कैटेगरी में {n} प्रोडक्ट। कीमत, स्टॉक और Buy खोलने के लिए "
              "बटन दबाएँ।",
        "ru": "Товаров в категории: {n}. Нажмите кнопку, чтобы открыть цену, "
              "наличие и покупку.",
        "zh": "此分类有 {n} 件商品。点击按钮查看价格、库存并购买。",
        "vi": "Danh mục này có {n} sản phẩm. Chạm một nút để xem giá, tồn kho "
              "và mua.",
    },
    "category_empty": {
        "en": "This category is empty right now.",
        "bn": "এই ক্যাটাগরি এখন খালি।",
        "hi": "यह कैटेगरी अभी खाली है।",
        "ru": "Эта категория пока пуста.",
        "zh": "此分类目前为空。",
        "vi": "Danh mục này hiện đang trống.",
    },
    "in_stock": {
        "en": "In stock ({n})", "bn": "স্টকে আছে ({n})",
        "hi": "स्टॉक में ({n})", "ru": "В наличии ({n})",
        "zh": "有库存 ({n})", "vi": "Còn hàng ({n})",
    },
    "out_of_stock": {
        "en": "Out of stock", "bn": "স্টক শেষ", "hi": "स्टॉक खत्म",
        "ru": "Нет в наличии", "zh": "已售罄", "vi": "Hết hàng",
    },
    "unlimited_stock": {
        "en": "Always in stock", "bn": "সবসময় স্টকে", "hi": "हमेशा उपलब्ध",
        "ru": "Всегда в наличии", "zh": "常备库存", "vi": "Luôn có hàng",
    },

    # product detail
    "pd_unit_price": {
        "en": "Unit price", "bn": "একক দাম", "hi": "प्रति यूनिट कीमत",
        "ru": "Цена за штуку", "zh": "单价", "vi": "Đơn giá",
    },
    "pd_stock": {
        "en": "Stock", "bn": "স্টক", "hi": "स्टॉक",
        "ru": "Наличие", "zh": "库存", "vi": "Tồn kho",
    },
    "pd_wallet": {
        "en": "Wallet", "bn": "ওয়ালেট", "hi": "वॉलेट",
        "ru": "Кошелёк", "zh": "钱包", "vi": "Ví",
    },
    "pd_sold": {
        "en": "Sold", "bn": "বিক্রি", "hi": "बिके",
        "ru": "Продано", "zh": "已售", "vi": "Đã bán",
    },
    "pd_sku": "SKU",
    "pd_delivery": {
        "en": "Delivery", "bn": "ডেলিভারি", "hi": "डिलीवरी",
        "ru": "Доставка", "zh": "交付", "vi": "Giao hàng",
    },
    "pd_delivery_instant": {
        "en": "Instant", "bn": "ইনস্ট্যান্ট", "hi": "तुरंत",
        "ru": "Моментально", "zh": "即时", "vi": "Tức thì",
    },
    "pd_delivery_manual": {
        "en": "Manual", "bn": "ম্যানুয়াল", "hi": "मैनुअल",
        "ru": "Вручную", "zh": "人工", "vi": "Thủ công",
    },
    "pd_warranty": {
        "en": "Warranty", "bn": "ওয়ারেন্টি", "hi": "वारंटी",
        "ru": "Гарантия", "zh": "保障", "vi": "Bảo hành",
    },
    "pd_qty_line": "Qty {min}–{max} · x{qty} = {total}",
    "pd_coupon_applied": {
        "en": "Coupon {code} applied — you save {amount}.",
        "bn": "কুপন {code} প্রয়োগ হয়েছে — সাশ্রয় {amount}।",
        "hi": "कूपन {code} लागू — बचत {amount}।",
        "ru": "Купон {code} применён — экономия {amount}.",
        "zh": "优惠券 {code} 已应用 — 省 {amount}。",
        "vi": "Đã áp mã {code} — tiết kiệm {amount}.",
    },
    "pd_sold_out_note": {
        "en": "Sold out. Alerts are on, so you will hear about the restock "
              "first.",
        "bn": "স্টক শেষ। অ্যালার্ট চালু আছে, রিস্টক হলে আগে জানবেন।",
        "hi": "स्टॉक खत्म। अलर्ट चालू है, रीस्टॉक की जानकारी पहले मिलेगी।",
        "ru": "Распродано. Уведомления включены — узнаете о поступлении первым.",
        "zh": "已售罄。提醒已开启，补货时会第一时间通知你。",
        "vi": "Đã hết hàng. Thông báo đang bật nên bạn sẽ biết tin về hàng mới.",
    },

    # ─── CONFIRM ──────────────────────────────────────────────
    "confirm_title": {
        "en": "Confirm order", "bn": "অর্ডার নিশ্চিত করুন",
        "hi": "ऑर्डर कन्फर्म करें", "ru": "Подтвердите заказ",
        "zh": "确认订单", "vi": "Xác nhận đơn hàng",
    },
    "confirm_qty": {
        "en": "Qty", "bn": "পরিমাণ", "hi": "मात्रा",
        "ru": "Кол-во", "zh": "数量", "vi": "SL",
    },
    "confirm_total": {
        "en": "Total", "bn": "মোট", "hi": "कुल",
        "ru": "Итого", "zh": "合计", "vi": "Tổng",
    },
    "confirm_discount": {
        "en": "Discount", "bn": "ডিসকাউন্ট", "hi": "छूट",
        "ru": "Скидка", "zh": "折扣", "vi": "Giảm giá",
    },
    "confirm_details": {
        "en": "Details", "bn": "বিস্তারিত", "hi": "विवरण",
        "ru": "Описание", "zh": "详情", "vi": "Chi tiết",
    },
    "confirm_delivery_note": {
        "en": "Delivery note", "bn": "ডেলিভারি নোট", "hi": "डिलीवरी नोट",
        "ru": "Примечание к доставке", "zh": "交付说明",
        "vi": "Ghi chú giao hàng",
    },
    "confirm_question": {
        "en": "Do you want to buy this quantity?",
        "bn": "আপনি কি এই পরিমাণ কিনতে চান?",
        "hi": "क्या आप यह मात्रा खरीदना चाहते हैं?",
        "ru": "Купить это количество?",
        "zh": "确认购买该数量吗？",
        "vi": "Bạn muốn mua số lượng này chứ?",
    },

    # ─── LOW BALANCE / PAY ────────────────────────────────────
    "low_title": {
        "en": "LOW BALANCE", "bn": "ব্যালেন্স কম", "hi": "बैलेंस कम",
        "ru": "НЕДОСТАТОЧНО СРЕДСТВ", "zh": "余额不足",
        "vi": "SỐ DƯ THẤP",
    },
    "low_help": {
        "en": "Pay the shortfall below to get this item, or open Wallet.",
        "bn": "এই আইটেম পেতে নিচে ঘাটতি পরিশোধ করুন, বা ওয়ালেট খুলুন।",
        "hi": "यह आइटम पाने के लिए नीचे शेष राशि भरें, या वॉलेट खोलें।",
        "ru": "Оплатите недостающую сумму ниже или откройте кошелёк.",
        "zh": "在下方支付差额即可获得商品，或打开钱包。",
        "vi": "Thanh toán phần còn thiếu bên dưới để nhận hàng, hoặc mở Ví.",
    },
    "low_need": {
        "en": "Need {short} more. Min top-up is {min}. Extra stays in wallet.",
        "bn": "আরও {short} দরকার। সর্বনিম্ন টপ-আপ {min}। বাকি টাকা ওয়ালেটে "
              "থাকবে।",
        "hi": "{short} और चाहिए। न्यूनतम टॉप-अप {min} है। अतिरिक्त राशि वॉलेट "
              "में रहेगी।",
        "ru": "Нужно ещё {short}. Минимальное пополнение — {min}. Остаток "
              "останется в кошельке.",
        "zh": "还需 {short}。最低充值 {min}。多余金额留在钱包。",
        "vi": "Cần thêm {short}. Nạp tối thiểu {min}. Phần dư vẫn nằm trong ví.",
    },
    "pay_title": {
        "en": "Pay and get item", "bn": "পেমেন্ট করে আইটেম নিন",
        "hi": "भुगतान करें और आइटम पाएँ", "ru": "Оплатить и получить товар",
        "zh": "支付并获取商品", "vi": "Thanh toán và nhận hàng",
    },
    "pay_product": {
        "en": "Product", "bn": "প্রোডাক্ট", "hi": "प्रोडक्ट",
        "ru": "Товар", "zh": "商品", "vi": "Sản phẩm",
    },
    "pay_order_total": {
        "en": "Order total", "bn": "অর্ডার মোট", "hi": "ऑर्डर कुल",
        "ru": "Сумма заказа", "zh": "订单总额", "vi": "Tổng đơn",
    },
    "pay_now": {
        "en": "Pay now", "bn": "এখন দিতে হবে", "hi": "अब भुगतान",
        "ru": "К оплате", "zh": "现在支付", "vi": "Cần trả",
    },
    "pay_pick": {
        "en": "Pick a payment method.",
        "bn": "একটি পেমেন্ট মেথড বাছুন।",
        "hi": "भुगतान का तरीका चुनें।",
        "ru": "Выберите способ оплаты.",
        "zh": "请选择支付方式。",
        "vi": "Chọn phương thức thanh toán.",
    },
    "pay_none": {
        "en": "No payment method is switched on yet. Use a gift code, or "
              "message support.",
        "bn": "এখনো কোনো পেমেন্ট মেথড চালু নেই। গিফট কোড ব্যবহার করুন বা "
              "সাপোর্টে লিখুন।",
        "hi": "अभी कोई भुगतान तरीका चालू नहीं है। गिफ्ट कोड इस्तेमाल करें या "
              "सपोर्ट से बात करें।",
        "ru": "Способы оплаты пока не подключены. Используйте подарочный код "
              "или напишите в поддержку.",
        "zh": "尚未启用任何支付方式。请使用礼品码或联系客服。",
        "vi": "Chưa bật phương thức thanh toán nào. Hãy dùng mã quà tặng hoặc "
              "liên hệ hỗ trợ.",
    },

    # ─── INVOICE ──────────────────────────────────────────────
    "invoice_title": {
        "en": "Payment created", "bn": "পেমেন্ট তৈরি হয়েছে",
        "hi": "भुगतान बन गया", "ru": "Платёж создан",
        "zh": "支付已创建", "vi": "Đã tạo thanh toán",
    },
    "invoice_amount": {
        "en": "Amount", "bn": "পরিমাণ", "hi": "राशि",
        "ru": "Сумма", "zh": "金额", "vi": "Số tiền",
    },
    "invoice_method": {
        "en": "Method", "bn": "মেথড", "hi": "तरीका",
        "ru": "Способ", "zh": "方式", "vi": "Phương thức",
    },
    "invoice_ref": {
        "en": "Reference", "bn": "রেফারেন্স", "hi": "रेफरेंस",
        "ru": "Номер", "zh": "单号", "vi": "Mã tham chiếu",
    },
    "invoice_open": {
        "en": "Tap the button to pay, then come back and press "
              "“I have paid”.",
        "bn": "পেমেন্ট করতে বাটনে চাপ দিন, তারপর ফিরে এসে “I have paid” চাপুন।",
        "hi": "भुगतान के लिए बटन दबाएँ, फिर वापस आकर “I have paid” दबाएँ।",
        "ru": "Нажмите кнопку для оплаты, затем вернитесь и нажмите "
              "«I have paid».",
        "zh": "点击按钮付款，然后返回并点击 “I have paid”。",
        "vi": "Bấm nút để trả, rồi quay lại và bấm “I have paid”.",
    },
    "invoice_manual": {
        "en": "Send the payment, then press “I have paid” and support will "
              "confirm it.",
        "bn": "পেমেন্ট পাঠান, তারপর “I have paid” চাপুন — সাপোর্ট নিশ্চিত করবে।",
        "hi": "भुगतान भेजें, फिर “I have paid” दबाएँ, सपोर्ट पुष्टि करेगा।",
        "ru": "Отправьте платёж, затем нажмите «I have paid» — поддержка "
              "подтвердит.",
        "zh": "完成付款后点击 “I have paid”，客服将进行确认。",
        "vi": "Hãy chuyển tiền, rồi bấm “I have paid” để hỗ trợ xác nhận.",
    },
    "invoice_checking": {
        "en": "Checking your payment…",
        "bn": "আপনার পেমেন্ট চেক করা হচ্ছে…",
        "hi": "आपका भुगतान जाँचा जा रहा है…",
        "ru": "Проверяем платёж…",
        "zh": "正在核对你的付款…",
        "vi": "Đang kiểm tra thanh toán…",
    },
    "invoice_not_paid": {
        "en": "Not paid yet. If you just sent it, wait a moment and press "
              "again.",
        "bn": "এখনো পেমেন্ট আসেনি। এইমাত্র পাঠালে একটু অপেক্ষা করে আবার চাপুন।",
        "hi": "अभी भुगतान नहीं मिला। अभी भेजा है तो थोड़ा रुककर दोबारा दबाएँ।",
        "ru": "Оплата ещё не поступила. Если только что отправили — подождите "
              "и нажмите снова.",
        "zh": "尚未收到付款。如果刚刚支付，请稍等后再试。",
        "vi": "Chưa nhận được thanh toán. Nếu vừa gửi, hãy đợi chút rồi bấm lại.",
    },
    "invoice_sent_to_support": {
        "en": "Sent to support for review. You will get a message here once "
              "it is confirmed.",
        "bn": "রিভিউয়ের জন্য সাপোর্টে পাঠানো হয়েছে। নিশ্চিত হলে এখানেই "
              "মেসেজ পাবেন।",
        "hi": "समीक्षा के लिए सपोर्ट को भेजा गया। पुष्टि होने पर यहीं संदेश "
              "मिलेगा।",
        "ru": "Отправлено в поддержку. Сообщим здесь после подтверждения.",
        "zh": "已提交客服审核，确认后会在此通知你。",
        "vi": "Đã gửi cho hỗ trợ xem xét. Bạn sẽ nhận tin ở đây khi xác nhận.",
    },

    # ─── WALLET ───────────────────────────────────────────────
    "wallet_title": {
        "en": "Wallet", "bn": "ওয়ালেট", "hi": "वॉलेट",
        "ru": "Кошелёк", "zh": "钱包", "vi": "Ví",
    },
    "wallet_balance": {
        "en": "Balance", "bn": "ব্যালেন্স", "hi": "बैलेंस",
        "ru": "Баланс", "zh": "余额", "vi": "Số dư",
    },
    "wallet_topped_up": {
        "en": "Topped up", "bn": "মোট টপ-আপ", "hi": "कुल टॉप-अप",
        "ru": "Пополнено", "zh": "累计充值", "vi": "Đã nạp",
    },
    "wallet_spent": {
        "en": "Spent", "bn": "খরচ", "hi": "खर्च",
        "ru": "Потрачено", "zh": "已消费", "vi": "Đã chi",
    },
    "wallet_intro": {
        "en": "Top up once, then buy anything without leaving the chat.",
        "bn": "একবার টপ-আপ করুন, তারপর চ্যাট ছাড়াই যা খুশি কিনুন।",
        "hi": "एक बार टॉप-अप करें, फिर चैट छोड़े बिना कुछ भी खरीदें।",
        "ru": "Пополните один раз и покупайте, не выходя из чата.",
        "zh": "一次充值，随后可在聊天内直接购买。",
        "vi": "Nạp một lần, rồi mua mọi thứ ngay trong chat.",
    },
    "wallet_min": {
        "en": "Min top-up is {min}.",
        "bn": "সর্বনিম্ন টপ-আপ {min}।",
        "hi": "न्यूनतम टॉप-अप {min} है।",
        "ru": "Минимальное пополнение — {min}.",
        "zh": "最低充值 {min}。",
        "vi": "Nạp tối thiểu {min}.",
    },
    "topup_title": {
        "en": "Top up", "bn": "টপ-আপ", "hi": "टॉप-अप",
        "ru": "Пополнение", "zh": "充值", "vi": "Nạp tiền",
    },
    "topup_pick": {
        "en": "Pick an amount, or send your own number in the chat.",
        "bn": "একটি পরিমাণ বাছুন, বা চ্যাটে নিজের সংখ্যা লিখুন।",
        "hi": "राशि चुनें, या चैट में अपनी राशि भेजें।",
        "ru": "Выберите сумму или отправьте свою в чат.",
        "zh": "选择金额，或在聊天中发送自定义金额。",
        "vi": "Chọn một mức, hoặc gửi số tiền của bạn vào chat.",
    },
    "topup_custom_prompt": {
        "en": "Send the amount you want to add (example: 5).",
        "bn": "যে পরিমাণ যোগ করতে চান লিখুন (যেমন: 5)।",
        "hi": "जो राशि जोड़नी है वह भेजें (उदाहरण: 5)।",
        "ru": "Отправьте сумму пополнения (например: 5).",
        "zh": "发送你想充值的金额（例如：5）。",
        "vi": "Gửi số tiền bạn muốn nạp (ví dụ: 5).",
    },
    "topup_too_small": {
        "en": "Minimum top-up is {min}.",
        "bn": "সর্বনিম্ন টপ-আপ {min}।",
        "hi": "न्यूनतम टॉप-अप {min} है।",
        "ru": "Минимальное пополнение — {min}.",
        "zh": "最低充值为 {min}。",
        "vi": "Nạp tối thiểu là {min}.",
    },
    "topup_too_big": {
        "en": "Maximum top-up is {max}. Message support for larger amounts.",
        "bn": "সর্বোচ্চ টপ-আপ {max}। বড় অঙ্কের জন্য সাপোর্টে লিখুন।",
        "hi": "अधिकतम टॉप-अप {max} है। बड़ी राशि के लिए सपोर्ट से बात करें।",
        "ru": "Максимальное пополнение — {max}. Для больших сумм напишите в "
              "поддержку.",
        "zh": "最高充值为 {max}。更大金额请联系客服。",
        "vi": "Nạp tối đa là {max}. Số lớn hơn hãy liên hệ hỗ trợ.",
    },
    "wallet_history_title": {
        "en": "Wallet history", "bn": "ওয়ালেট হিস্ট্রি", "hi": "वॉलेट इतिहास",
        "ru": "История кошелька", "zh": "钱包记录", "vi": "Lịch sử ví",
    },
    "wallet_history_empty": {
        "en": "No top-ups yet.",
        "bn": "এখনো কোনো টপ-আপ নেই।",
        "hi": "अभी कोई टॉप-अप नहीं।",
        "ru": "Пополнений пока нет.",
        "zh": "暂无充值记录。",
        "vi": "Chưa có lần nạp nào.",
    },
    "wallet_funded_dm": {
        "en": "{amount} added to your wallet. New balance: {balance}.",
        "bn": "আপনার ওয়ালেটে {amount} যোগ হয়েছে। নতুন ব্যালেন্স: {balance}।",
        "hi": "आपके वॉलेट में {amount} जोड़ा गया। नया बैलेंस: {balance}।",
        "ru": "На кошелёк зачислено {amount}. Новый баланс: {balance}.",
        "zh": "已向你的钱包充入 {amount}。新余额：{balance}。",
        "vi": "Đã thêm {amount} vào ví. Số dư mới: {balance}.",
    },

    # ─── ORDERS ───────────────────────────────────────────────
    "orders_title": {
        "en": "Orders", "bn": "অর্ডার", "hi": "ऑर्डर",
        "ru": "Заказы", "zh": "订单", "vi": "Đơn hàng",
    },
    "orders_intro": {
        "en": "Your last {n} purchase(s). Tap one to open it.",
        "bn": "আপনার সর্বশেষ {n} টি কেনাকাটা। খুলতে চাপ দিন।",
        "hi": "आपकी पिछली {n} खरीदारी। खोलने के लिए टैप करें।",
        "ru": "Ваши последние покупки: {n}. Нажмите, чтобы открыть.",
        "zh": "你最近的 {n} 笔购买。点击查看。",
        "vi": "{n} giao dịch gần nhất của bạn. Chạm để mở.",
    },
    "orders_empty": {
        "en": "No orders yet. Open Products to make your first one.",
        "bn": "এখনো কোনো অর্ডার নেই। প্রথমটি করতে Products খুলুন।",
        "hi": "अभी कोई ऑर्डर नहीं। पहला ऑर्डर करने के लिए Products खोलें।",
        "ru": "Заказов пока нет. Откройте «Товары», чтобы сделать первый.",
        "zh": "暂无订单。打开商品即可下第一单。",
        "vi": "Chưa có đơn nào. Mở Sản phẩm để đặt đơn đầu tiên.",
    },
    "order_title": {
        "en": "Order", "bn": "অর্ডার", "hi": "ऑर्डर",
        "ru": "Заказ", "zh": "订单", "vi": "Đơn hàng",
    },
    "order_status": {
        "en": "Status", "bn": "স্ট্যাটাস", "hi": "स्थिति",
        "ru": "Статус", "zh": "状态", "vi": "Trạng thái",
    },
    "order_date": {
        "en": "Date", "bn": "তারিখ", "hi": "तारीख",
        "ru": "Дата", "zh": "日期", "vi": "Ngày",
    },
    "status_delivered": {
        "en": "Delivered", "bn": "ডেলিভারড", "hi": "डिलीवर हो गया",
        "ru": "Доставлен", "zh": "已交付", "vi": "Đã giao",
    },
    "status_pending": {
        "en": "Pending", "bn": "পেন্ডিং", "hi": "लंबित",
        "ru": "В обработке", "zh": "处理中", "vi": "Đang chờ",
    },
    "status_manual": {
        "en": "Waiting for support", "bn": "সাপোর্টের অপেক্ষায়",
        "hi": "सपोर्ट की प्रतीक्षा", "ru": "Ожидает поддержку",
        "zh": "等待客服处理", "vi": "Đang chờ hỗ trợ",
    },
    "status_cancelled": {
        "en": "Cancelled", "bn": "বাতিল", "hi": "रद्द",
        "ru": "Отменён", "zh": "已取消", "vi": "Đã huỷ",
    },

    # ─── DELIVERY ─────────────────────────────────────────────
    "delivered_title": {
        "en": "DELIVERED", "bn": "ডেলিভারড", "hi": "डिलीवर हो गया",
        "ru": "ДОСТАВЛЕНО", "zh": "已交付", "vi": "ĐÃ GIAO",
    },
    "delivered_items": {
        "en": "Your item(s)", "bn": "আপনার আইটেম", "hi": "आपके आइटम",
        "ru": "Ваши товары", "zh": "你的商品", "vi": "Hàng của bạn",
    },
    "delivered_keep": {
        "en": "Save this message. Warranty claims need the order id above.",
        "bn": "এই মেসেজ সেভ করে রাখুন। ওয়ারেন্টি ক্লেইমে উপরের অর্ডার আইডি লাগবে।",
        "hi": "यह संदेश सेव रखें। वारंटी क्लेम के लिए ऊपर का ऑर्डर आईडी चाहिए।",
        "ru": "Сохраните это сообщение — для гарантии нужен номер заказа выше.",
        "zh": "请保存此消息。保障申请需要上面的订单号。",
        "vi": "Hãy lưu tin này. Yêu cầu bảo hành cần mã đơn ở trên.",
    },
    "delivered_manual": {
        "en": "Paid. Support is preparing this item by hand and will send it "
              "in this chat.",
        "bn": "পেমেন্ট হয়েছে। সাপোর্ট আইটেমটি ম্যানুয়ালি প্রস্তুত করে এই "
              "চ্যাটে পাঠাবে।",
        "hi": "भुगतान हो गया। सपोर्ट इस आइटम को मैनुअली तैयार कर इसी चैट में "
              "भेजेगा।",
        "ru": "Оплачено. Поддержка готовит товар вручную и отправит его в "
              "этот чат.",
        "zh": "已付款。客服正在人工准备商品，并会在此聊天发送。",
        "vi": "Đã thanh toán. Hỗ trợ đang chuẩn bị thủ công và sẽ gửi vào chat.",
    },

    # ─── GIFT CODE ────────────────────────────────────────────
    "gift_title": {
        "en": "Gift code", "bn": "গিফট কোড", "hi": "गिफ्ट कोड",
        "ru": "Подарочный код", "zh": "礼品码", "vi": "Mã quà tặng",
    },
    "gift_intro": {
        "en": "Send the gift code in this chat and the value lands in your "
              "wallet.",
        "bn": "এই চ্যাটে গিফট কোড পাঠান, টাকা সোজা আপনার ওয়ালেটে যাবে।",
        "hi": "इस चैट में गिफ्ट कोड भेजें, राशि सीधे आपके वॉलेट में आएगी।",
        "ru": "Отправьте подарочный код в чат — сумма зачислится на кошелёк.",
        "zh": "在此聊天发送礼品码，金额会进入你的钱包。",
        "vi": "Gửi mã quà tặng vào chat, giá trị sẽ vào ví của bạn.",
    },
    "gift_send_now": {
        "en": "Send the code now — it looks like GIFT-A1B2C3D4.",
        "bn": "কোডটি এখন পাঠান — দেখতে এমন: GIFT-A1B2C3D4।",
        "hi": "कोड अब भेजें — यह ऐसा दिखता है: GIFT-A1B2C3D4।",
        "ru": "Отправьте код сейчас — он выглядит так: GIFT-A1B2C3D4.",
        "zh": "现在发送礼品码，格式如 GIFT-A1B2C3D4。",
        "vi": "Gửi mã ngay — dạng như GIFT-A1B2C3D4.",
    },
    "gift_ok": {
        "en": "{amount} credited. New balance: {balance}.",
        "bn": "{amount} জমা হয়েছে। নতুন ব্যালেন্স: {balance}।",
        "hi": "{amount} जुड़ गया। नया बैलेंस: {balance}।",
        "ru": "Зачислено {amount}. Новый баланс: {balance}.",
        "zh": "已入账 {amount}。新余额：{balance}。",
        "vi": "Đã cộng {amount}. Số dư mới: {balance}.",
    },
    "gift_unknown": {
        "en": "That code does not exist.",
        "bn": "এই কোডটি নেই।",
        "hi": "यह कोड मौजूद नहीं है।",
        "ru": "Такого кода нет.",
        "zh": "该码不存在。",
        "vi": "Mã này không tồn tại.",
    },
    "gift_expired": {
        "en": "That code has expired.",
        "bn": "কোডের সময় শেষ।",
        "hi": "यह कोड समाप्त हो चुका है।",
        "ru": "Код истёк.",
        "zh": "该码已过期。",
        "vi": "Mã đã hết hạn.",
    },
    "gift_already": {
        "en": "You already used that code.",
        "bn": "আপনি এই কোড আগেই ব্যবহার করেছেন।",
        "hi": "आपने यह कोड पहले ही उपयोग किया है।",
        "ru": "Вы уже использовали этот код.",
        "zh": "你已使用过该码。",
        "vi": "Bạn đã dùng mã này.",
    },
    "gift_used_up": {
        "en": "That code has run out of uses.",
        "bn": "কোডের ব্যবহার সীমা শেষ।",
        "hi": "इस कोड की उपयोग सीमा खत्म है।",
        "ru": "Лимит использований кода исчерпан.",
        "zh": "该码使用次数已用完。",
        "vi": "Mã đã hết lượt dùng.",
    },

    # ─── COUPON ───────────────────────────────────────────────
    "coupon_title": {
        "en": "Apply coupon", "bn": "কুপন প্রয়োগ", "hi": "कूपन लगाएँ",
        "ru": "Применить купон", "zh": "使用优惠券", "vi": "Áp mã giảm giá",
    },
    "coupon_prompt": {
        "en": "Send the coupon code for this product.",
        "bn": "এই প্রোডাক্টের কুপন কোড পাঠান।",
        "hi": "इस प्रोडक्ट के लिए कूपन कोड भेजें।",
        "ru": "Отправьте код купона для этого товара.",
        "zh": "发送此商品的优惠券码。",
        "vi": "Gửi mã giảm giá cho sản phẩm này.",
    },
    "coupon_unknown": {
        "en": "That coupon does not exist.",
        "bn": "এই কুপনটি নেই।",
        "hi": "यह कूपन मौजूद नहीं है।",
        "ru": "Такого купона нет.",
        "zh": "该优惠券不存在。",
        "vi": "Mã này không tồn tại.",
    },
    "coupon_expired": {
        "en": "That coupon has expired.",
        "bn": "কুপনের সময় শেষ।",
        "hi": "यह कूपन समाप्त हो चुका है।",
        "ru": "Купон истёк.",
        "zh": "该优惠券已过期。",
        "vi": "Mã đã hết hạn.",
    },
    "coupon_used_up": {
        "en": "That coupon has run out of uses.",
        "bn": "কুপনের ব্যবহার সীমা শেষ।",
        "hi": "इस कूपन की सीमा खत्म है।",
        "ru": "Лимит купона исчерпан.",
        "zh": "该优惠券次数已用完。",
        "vi": "Mã đã hết lượt dùng.",
    },
    "coupon_other_product": {
        "en": "That coupon belongs to a different product.",
        "bn": "এই কুপন অন্য প্রোডাক্টের জন্য।",
        "hi": "यह कूपन दूसरे प्रोडक्ट का है।",
        "ru": "Этот купон для другого товара.",
        "zh": "该优惠券属于其他商品。",
        "vi": "Mã này thuộc sản phẩm khác.",
    },
    "coupon_zero": {
        "en": "That coupon gives no discount here.",
        "bn": "এখানে এই কুপনে কোনো ছাড় নেই।",
        "hi": "यहाँ इस कूपन से कोई छूट नहीं है।",
        "ru": "Этот купон здесь не даёт скидки.",
        "zh": "该优惠券在此无折扣。",
        "vi": "Mã này không giảm gì ở đây.",
    },
    "coupon_cleared": {
        "en": "Coupon removed.",
        "bn": "কুপন সরানো হয়েছে।",
        "hi": "कूपन हटा दिया गया।",
        "ru": "Купон убран.",
        "zh": "已移除优惠券。",
        "vi": "Đã bỏ mã giảm giá.",
    },

    # ─── SUPPORT / PROFILE / LANGUAGE ─────────────────────────
    "support_title": {
        "en": "Support", "bn": "সাপোর্ট", "hi": "सपोर्ट",
        "ru": "Поддержка", "zh": "客服", "vi": "Hỗ trợ",
    },
    "support_intro": {
        "en": "Payment stuck, item missing or a warranty problem — send your "
              "order id and a screenshot.",
        "bn": "পেমেন্ট আটকে আছে, আইটেম পাননি বা ওয়ারেন্টি সমস্যা — অর্ডার "
              "আইডি ও স্ক্রিনশট পাঠান।",
        "hi": "भुगतान अटका, आइटम नहीं मिला या वारंटी समस्या — ऑर्डर आईडी और "
              "स्क्रीनशॉट भेजें।",
        "ru": "Платёж застрял, товар не пришёл или вопрос по гарантии — "
              "пришлите номер заказа и скриншот.",
        "zh": "付款卡住、商品未收到或保障问题 — 请发送订单号和截图。",
        "vi": "Thanh toán bị treo, thiếu hàng hay bảo hành — gửi mã đơn và "
              "ảnh chụp.",
    },
    "support_hours": {
        "en": "Replies usually come within a few hours.",
        "bn": "সাধারণত কয়েক ঘণ্টার মধ্যে উত্তর পাবেন।",
        "hi": "जवाब आमतौर पर कुछ घंटों में मिलता है।",
        "ru": "Обычно отвечаем в течение нескольких часов.",
        "zh": "通常几小时内回复。",
        "vi": "Thường trả lời trong vài giờ.",
    },
    "profile_title": {
        "en": "Profile", "bn": "প্রোফাইল", "hi": "प्रोफ़ाइल",
        "ru": "Профиль", "zh": "个人资料", "vi": "Trang cá nhân",
    },
    "profile_name": {
        "en": "Name", "bn": "নাম", "hi": "नाम",
        "ru": "Имя", "zh": "名称", "vi": "Tên",
    },
    "profile_id": {
        "en": "User id", "bn": "ইউজার আইডি", "hi": "यूज़र आईडी",
        "ru": "ID пользователя", "zh": "用户 ID", "vi": "ID người dùng",
    },
    "profile_orders": {
        "en": "Orders", "bn": "অর্ডার", "hi": "ऑर्डर",
        "ru": "Заказы", "zh": "订单", "vi": "Đơn hàng",
    },
    "profile_joined": {
        "en": "Joined", "bn": "যোগ দিয়েছেন", "hi": "जुड़े",
        "ru": "Регистрация", "zh": "加入时间", "vi": "Tham gia",
    },
    "profile_language": {
        "en": "Language", "bn": "ভাষা", "hi": "भाषा",
        "ru": "Язык", "zh": "语言", "vi": "Ngôn ngữ",
    },
    "lang_title": {
        "en": "Language", "bn": "ভাষা", "hi": "भाषा",
        "ru": "Язык", "zh": "语言", "vi": "Ngôn ngữ",
    },
    "lang_intro": {
        "en": "Pick the language for this bot.",
        "bn": "এই বটের ভাষা বাছুন।",
        "hi": "इस बॉट की भाषा चुनें।",
        "ru": "Выберите язык бота.",
        "zh": "选择机器人的语言。",
        "vi": "Chọn ngôn ngữ cho bot này.",
    },
    "lang_set": {
        "en": "Language set to {name}.",
        "bn": "ভাষা {name} করা হয়েছে।",
        "hi": "भाषा {name} कर दी गई।",
        "ru": "Язык изменён на {name}.",
        "zh": "语言已设为 {name}。",
        "vi": "Đã đặt ngôn ngữ {name}.",
    },

    # ─── API KEY SCREEN ───────────────────────────────────────
    "api_title": {
        "en": "Catalog API", "bn": "ক্যাটালগ API", "hi": "कैटलॉग API",
        "ru": "API каталога", "zh": "目录 API", "vi": "API danh mục",
    },
    "api_off": {
        "en": "The catalog API is switched off. Ask support if you need "
              "programmatic access to prices and stock.",
        "bn": "ক্যাটালগ API বন্ধ আছে। প্রাইস ও স্টকের API অ্যাক্সেস দরকার হলে "
              "সাপোর্টে লিখুন।",
        "hi": "कैटलॉग API बंद है। कीमत और स्टॉक के API एक्सेस के लिए सपोर्ट से "
              "बात करें।",
        "ru": "API каталога отключён. Напишите в поддержку, если нужен "
              "программный доступ к ценам и наличию.",
        "zh": "目录 API 已关闭。如需以程序方式获取价格与库存，请联系客服。",
        "vi": "API danh mục đang tắt. Liên hệ hỗ trợ nếu bạn cần truy cập "
              "giá và tồn kho bằng API.",
    },
    "api_on": {
        "en": "Read-only catalog feed. Ask support for a key, then call the "
              "endpoint below with header X-API-Key.",
        "bn": "রিড-অনলি ক্যাটালগ ফিড। সাপোর্ট থেকে key নিয়ে নিচের endpoint-এ "
              "X-API-Key হেডার দিয়ে কল করুন।",
        "hi": "रीड-ओनली कैटलॉग फीड। सपोर्ट से key लें, फिर नीचे के endpoint पर "
              "X-API-Key हेडर के साथ कॉल करें।",
        "ru": "Каталог только для чтения. Запросите ключ у поддержки и "
              "вызывайте endpoint ниже с заголовком X-API-Key.",
        "zh": "只读目录接口。向客服索取 key，然后带 X-API-Key 请求下方地址。",
        "vi": "Nguồn danh mục chỉ đọc. Xin key từ hỗ trợ, rồi gọi endpoint "
              "bên dưới với header X-API-Key.",
    },

    # ─── FORCE JOIN / BANS / ERRORS ───────────────────────────
    "join_title": {
        "en": "One step first", "bn": "প্রথমে একটি ধাপ",
        "hi": "पहले एक कदम", "ru": "Сначала один шаг",
        "zh": "先完成一步", "vi": "Một bước trước đã",
    },
    "join_intro": {
        "en": "Join {channel} to use the shop, then press “I have joined”.",
        "bn": "শপ ব্যবহার করতে {channel} এ জয়েন করুন, তারপর “I have joined” "
              "চাপুন।",
        "hi": "शॉप इस्तेमाल करने के लिए {channel} जॉइन करें, फिर "
              "“I have joined” दबाएँ।",
        "ru": "Подпишитесь на {channel}, затем нажмите «I have joined».",
        "zh": "加入 {channel} 后点击 “I have joined” 即可使用商店。",
        "vi": "Hãy tham gia {channel} để dùng shop, rồi bấm “I have joined”.",
    },
    "join_not_yet": {
        "en": "Not there yet. Join the channel first.",
        "bn": "এখনো জয়েন হয়নি। আগে চ্যানেলে জয়েন করুন।",
        "hi": "अभी जॉइन नहीं हुआ। पहले चैनल जॉइन करें।",
        "ru": "Пока не видно подписки. Сначала подпишитесь.",
        "zh": "尚未加入，请先加入频道。",
        "vi": "Chưa thấy bạn tham gia. Hãy vào kênh trước.",
    },
    "banned_title": {
        "en": "Account blocked", "bn": "অ্যাকাউন্ট ব্লকড",
        "hi": "खाता ब्लॉक", "ru": "Аккаунт заблокирован",
        "zh": "账号已封禁", "vi": "Tài khoản bị chặn",
    },
    "banned_body": {
        "en": "This account cannot use the shop. Reason: {reason}",
        "bn": "এই অ্যাকাউন্ট শপ ব্যবহার করতে পারবে না। কারণ: {reason}",
        "hi": "यह खाता शॉप इस्तेमाल नहीं कर सकता। कारण: {reason}",
        "ru": "Этот аккаунт не может пользоваться магазином. Причина: {reason}",
        "zh": "该账号无法使用商店。原因：{reason}",
        "vi": "Tài khoản này không thể dùng shop. Lý do: {reason}",
    },
    "err_generic": {
        "en": "Something went wrong. Try again.",
        "bn": "কিছু ভুল হয়েছে। আবার চেষ্টা করুন।",
        "hi": "कुछ गलत हो गया। दोबारा कोशिश करें।",
        "ru": "Что-то пошло не так. Попробуйте снова.",
        "zh": "出错了，请重试。",
        "vi": "Có lỗi xảy ra. Hãy thử lại.",
    },
    "err_not_found": {
        "en": "That is gone. Open Products again.",
        "bn": "এটি আর নেই। আবার Products খুলুন।",
        "hi": "यह अब नहीं है। फिर से Products खोलें।",
        "ru": "Этого больше нет. Откройте «Товары» снова.",
        "zh": "该内容已不存在，请重新打开商品。",
        "vi": "Mục này không còn. Hãy mở lại Sản phẩm.",
    },
    "err_no_stock": {
        "en": "Out of stock. Alerts are on, so you will hear about the "
              "restock.",
        "bn": "স্টক শেষ। অ্যালার্ট চালু আছে, রিস্টক হলে জানবেন।",
        "hi": "स्टॉक खत्म। अलर्ट चालू है, रीस्टॉक पर बता देंगे।",
        "ru": "Нет в наличии. Уведомления включены — сообщим о поступлении.",
        "zh": "已售罄。提醒已开启，补货时会通知你。",
        "vi": "Hết hàng. Thông báo đang bật nên bạn sẽ được nhắc khi có hàng.",
    },
    "err_stock_short": {
        "en": "Only {n} left. Lower the quantity.",
        "bn": "মাত্র {n} টি আছে। পরিমাণ কমান।",
        "hi": "केवल {n} बचे हैं। मात्रा घटाएँ।",
        "ru": "Осталось всего {n}. Уменьшите количество.",
        "zh": "仅剩 {n} 件，请减少数量。",
        "vi": "Chỉ còn {n}. Hãy giảm số lượng.",
    },
    "err_qty_range": {
        "en": "Quantity must be between {min} and {max}.",
        "bn": "পরিমাণ {min} থেকে {max} এর মধ্যে হতে হবে।",
        "hi": "मात्रा {min} से {max} के बीच होनी चाहिए।",
        "ru": "Количество должно быть от {min} до {max}.",
        "zh": "数量必须在 {min} 到 {max} 之间。",
        "vi": "Số lượng phải từ {min} đến {max}.",
    },
    "err_bad_number": {
        "en": "Send a number, for example 5.",
        "bn": "একটি সংখ্যা পাঠান, যেমন 5।",
        "hi": "एक संख्या भेजें, जैसे 5।",
        "ru": "Отправьте число, например 5.",
        "zh": "请发送一个数字，例如 5。",
        "vi": "Hãy gửi một con số, ví dụ 5.",
    },
    "err_admin_only": "Admins only.",
    "cancelled": {
        "en": "Cancelled.", "bn": "বাতিল করা হয়েছে।", "hi": "रद्द कर दिया।",
        "ru": "Отменено.", "zh": "已取消。", "vi": "Đã huỷ.",
    },
    "alerts_on": {
        "en": "Alerts on — you will hear about restocks and price drops.",
        "bn": "অ্যালার্ট চালু — রিস্টক ও দাম কমার খবর পাবেন।",
        "hi": "अलर्ट चालू — रीस्टॉक और कीमत घटने पर बताएँगे।",
        "ru": "Уведомления включены — сообщим о поступлении и снижении цены.",
        "zh": "提醒已开启 — 补货和降价时通知你。",
        "vi": "Đã bật thông báo — bạn sẽ biết khi có hàng hoặc giảm giá.",
    },
    "alerts_off": {
        "en": "Alerts off for this product.",
        "bn": "এই প্রোডাক্টের অ্যালার্ট বন্ধ।",
        "hi": "इस प्रोडक्ट के अलर्ट बंद।",
        "ru": "Уведомления по этому товару отключены.",
        "zh": "已关闭该商品的提醒。",
        "vi": "Đã tắt thông báo cho sản phẩm này.",
    },

    # ─── BUTTONS ──────────────────────────────────────────────
    "btn_products": {
        "en": "Products", "bn": "প্রোডাক্ট", "hi": "प्रोडक्ट",
        "ru": "Товары", "zh": "商品", "vi": "Sản phẩm",
    },
    "btn_wallet": {
        "en": "Wallet", "bn": "ওয়ালেট", "hi": "वॉलेट",
        "ru": "Кошелёк", "zh": "钱包", "vi": "Ví",
    },
    "btn_orders": {
        "en": "Orders", "bn": "অর্ডার", "hi": "ऑर्डर",
        "ru": "Заказы", "zh": "订单", "vi": "Đơn hàng",
    },
    "btn_gift": {
        "en": "Gift code", "bn": "গিফট কোড", "hi": "गिफ्ट कोड",
        "ru": "Подарочный код", "zh": "礼品码", "vi": "Mã quà tặng",
    },
    "btn_support": {
        "en": "Support", "bn": "সাপোর্ট", "hi": "सपोर्ट",
        "ru": "Поддержка", "zh": "客服", "vi": "Hỗ trợ",
    },
    "btn_profile": {
        "en": "Profile", "bn": "প্রোফাইল", "hi": "प्रोफ़ाइल",
        "ru": "Профиль", "zh": "个人资料", "vi": "Trang cá nhân",
    },
    "btn_language": {
        "en": "Language", "bn": "ভাষা", "hi": "भाषा",
        "ru": "Язык", "zh": "语言", "vi": "Ngôn ngữ",
    },
    "btn_home": {
        "en": "Home", "bn": "হোম", "hi": "होम",
        "ru": "Домой", "zh": "主页", "vi": "Trang chính",
    },
    "btn_back": {
        "en": "Back", "bn": "ব্যাক", "hi": "वापस",
        "ru": "Назад", "zh": "返回", "vi": "Quay lại",
    },
    "btn_close": {
        "en": "Close", "bn": "বন্ধ", "hi": "बंद करें",
        "ru": "Закрыть", "zh": "关闭", "vi": "Đóng",
    },
    "btn_refresh": {
        "en": "Refresh", "bn": "রিফ্রেশ", "hi": "रिफ्रेश",
        "ru": "Обновить", "zh": "刷新", "vi": "Làm mới",
    },
    "btn_api_key": {
        "en": "API Key", "bn": "API Key", "hi": "API Key",
        "ru": "API-ключ", "zh": "API 密钥", "vi": "API Key",
    },
    "btn_catalog": {
        "en": "Catalog", "bn": "ক্যাটালগ", "hi": "कैटलॉग",
        "ru": "Каталог", "zh": "目录", "vi": "Danh mục",
    },
    "btn_custom": {
        "en": "Custom", "bn": "কাস্টম", "hi": "कस्टम",
        "ru": "Другое", "zh": "自定义", "vi": "Tuỳ chọn",
    },
    "btn_apply_coupon": {
        "en": "Apply coupon", "bn": "কুপন দিন", "hi": "कूपन लगाएँ",
        "ru": "Применить купон", "zh": "使用优惠券", "vi": "Áp mã",
    },
    "btn_remove_coupon": {
        "en": "Remove coupon", "bn": "কুপন সরান", "hi": "कूपन हटाएँ",
        "ru": "Убрать купон", "zh": "移除优惠券", "vi": "Bỏ mã",
    },
    "btn_stop_alerts": {
        "en": "Stop Alerts", "bn": "অ্যালার্ট বন্ধ", "hi": "अलर्ट बंद करें",
        "ru": "Отключить уведомления", "zh": "关闭提醒",
        "vi": "Tắt thông báo",
    },
    "btn_get_alerts": {
        "en": "Get Alerts", "bn": "অ্যালার্ট চালু", "hi": "अलर्ट चालू करें",
        "ru": "Включить уведомления", "zh": "开启提醒",
        "vi": "Bật thông báo",
    },
    "btn_delivery_note": {
        "en": "Delivery note", "bn": "ডেলিভারি নোট", "hi": "डिलीवरी नोट",
        "ru": "О доставке", "zh": "交付说明", "vi": "Ghi chú giao hàng",
    },
    "btn_yes_buy": {
        "en": "Yes, buy now", "bn": "হ্যাঁ, এখন কিনুন",
        "hi": "हाँ, अभी खरीदें", "ru": "Да, купить",
        "zh": "是，立即购买", "vi": "Có, mua ngay",
    },
    "btn_no_cancel": {
        "en": "No, cancel", "bn": "না, বাতিল", "hi": "नहीं, रद्द करें",
        "ru": "Нет, отмена", "zh": "不，取消", "vi": "Không, huỷ",
    },
    "btn_pay_and_get": {
        "en": "Pay {amount} and get item",
        "bn": "{amount} দিয়ে আইটেম নিন",
        "hi": "{amount} देकर आइटम लें",
        "ru": "Оплатить {amount} и получить",
        "zh": "支付 {amount} 获取商品",
        "vi": "Trả {amount} và nhận hàng",
    },
    "btn_open_wallet": {
        "en": "Open wallet", "bn": "ওয়ালেট খুলুন", "hi": "वॉलेट खोलें",
        "ru": "Открыть кошелёк", "zh": "打开钱包", "vi": "Mở ví",
    },
    "btn_product": {
        "en": "Product", "bn": "প্রোডাক্ট", "hi": "प्रोडक्ट",
        "ru": "Товар", "zh": "商品", "vi": "Sản phẩm",
    },
    "btn_topup": {
        "en": "Top up", "bn": "টপ-আপ", "hi": "टॉप-अप",
        "ru": "Пополнить", "zh": "充值", "vi": "Nạp tiền",
    },
    "btn_history": {
        "en": "History", "bn": "হিস্ট্রি", "hi": "इतिहास",
        "ru": "История", "zh": "记录", "vi": "Lịch sử",
    },
    "btn_i_paid": {
        "en": "I have paid", "bn": "আমি পেমেন্ট করেছি",
        "hi": "मैंने भुगतान कर दिया", "ru": "Я оплатил",
        "zh": "我已付款", "vi": "Tôi đã trả",
    },
    "btn_open_invoice": {
        "en": "Pay now", "bn": "এখন পে করুন", "hi": "अभी भुगतान करें",
        "ru": "Оплатить", "zh": "立即支付", "vi": "Thanh toán",
    },
    "btn_cancel": {
        "en": "Cancel", "bn": "বাতিল", "hi": "रद्द करें",
        "ru": "Отмена", "zh": "取消", "vi": "Huỷ",
    },
    "btn_contact_support": {
        "en": "Message support", "bn": "সাপোর্টে মেসেজ",
        "hi": "सपोर्ट को लिखें", "ru": "Написать в поддержку",
        "zh": "联系客服", "vi": "Nhắn hỗ trợ",
    },
    "btn_resend": {
        "en": "Resend delivery", "bn": "ডেলিভারি আবার পাঠান",
        "hi": "डिलीवरी दोबारा भेजें", "ru": "Отправить снова",
        "zh": "重新发送交付", "vi": "Gửi lại hàng",
    },
    "btn_visit_bot": {
        "en": "Visit bot", "bn": "বট খুলুন", "hi": "बॉट खोलें",
        "ru": "Открыть бота", "zh": "打开机器人", "vi": "Mở bot",
    },
    "btn_buy_now": {
        "en": "Buy now", "bn": "এখন কিনুন", "hi": "अभी खरीदें",
        "ru": "Купить", "zh": "立即购买", "vi": "Mua ngay",
    },
    "btn_joined": {
        "en": "I have joined", "bn": "আমি জয়েন করেছি",
        "hi": "मैं जॉइन कर चुका", "ru": "Я подписался",
        "zh": "我已加入", "vi": "Tôi đã tham gia",
    },
    "btn_join_channel": {
        "en": "Join channel", "bn": "চ্যানেলে জয়েন", "hi": "चैनल जॉइन करें",
        "ru": "Подписаться", "zh": "加入频道", "vi": "Vào kênh",
    },

    # ─── CHANNEL POSTS ────────────────────────────────────────
    "bc_funded_title": "WALLET FUNDED",
    "bc_funded_amount": "Amount",
    "bc_funded_customer": "Customer",
    "bc_funded_method": "Method",
    "bc_funded_line1": "A customer just added funds.",
    "bc_funded_line2": "Shop is live — join and top up anytime.",
    "bc_order_title": "NEW ORDER",
    "bc_order_product": "Product",
    "bc_order_qty": "Qty",
    "bc_order_paid": "Paid",
    "bc_order_customer": "Customer",
    "bc_order_line1": "A customer just completed this order.",
    "bc_order_line2": "The shop is live — tap below to buy the same product.",
    "bc_gone_title": "ALMOST GONE",
    "bc_gone_left": "Only {n} items left in stock.",
    "bc_gone_price": "Price",
    "bc_gone_final": "This is your final chance — secure it before it is "
                     "sold out for good.",
    "bc_restock_title": "BACK IN STOCK",
    "bc_restock_line": "{n} unit(s) just landed.",
    "bc_restock_hurry": "First come, first served.",

    # ─── HELP / TERMS ─────────────────────────────────────────
    "help_title": {
        "en": "How this bot works", "bn": "এই বট কীভাবে কাজ করে",
        "hi": "यह बॉट कैसे काम करता है", "ru": "Как работает бот",
        "zh": "本机器人怎么用", "vi": "Bot này hoạt động thế nào",
    },
    "help_steps": {
        "en": "1. Top up your wallet.\n"
              "2. Open Products and pick a category.\n"
              "3. Choose quantity and confirm.\n"
              "4. Delivery arrives in this chat right away.",
        "bn": "১. ওয়ালেট টপ-আপ করুন।\n"
              "২. Products খুলে ক্যাটাগরি বাছুন।\n"
              "৩. পরিমাণ বেছে কনফার্ম করুন।\n"
              "৪. ডেলিভারি সাথে সাথে এই চ্যাটে আসবে।",
        "hi": "1. वॉलेट टॉप-अप करें।\n"
              "2. Products खोलकर कैटेगरी चुनें।\n"
              "3. मात्रा चुनकर कन्फर्म करें।\n"
              "4. डिलीवरी तुरंत इसी चैट में आएगी।",
        "ru": "1. Пополните кошелёк.\n"
              "2. Откройте «Товары» и выберите категорию.\n"
              "3. Укажите количество и подтвердите.\n"
              "4. Доставка придёт в этот чат сразу.",
        "zh": "1. 为钱包充值。\n2. 打开商品并选择分类。\n"
              "3. 选择数量并确认。\n4. 商品立即发送到本聊天。",
        "vi": "1. Nạp tiền vào ví.\n2. Mở Sản phẩm và chọn danh mục.\n"
              "3. Chọn số lượng và xác nhận.\n"
              "4. Hàng được gửi ngay trong chat này.",
    },
    "terms_title": {
        "en": "Terms", "bn": "শর্তাবলী", "hi": "नियम",
        "ru": "Условия", "zh": "条款", "vi": "Điều khoản",
    },
    "terms_default": (
        "By buying here you agree that:\n\n"
        "• Read the product name, duration and warranty before you buy.\n"
        "• Delivery is instant for stocked items; manual items are prepared "
        "by support.\n"
        "• Refunds apply only when an item cannot be delivered or activated, "
        "or while it is still under its stated warranty.\n"
        "• Do not change the password or recovery mail of a delivered "
        "account unless support tells you to.\n"
        "• Keep your order id — warranty claims need it.\n"
        "• Stock can run out at any time; prices can change without notice."
    ),
}


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Look up a string. Unknown keys return the key itself so a typo shows up
    on screen instead of raising in a handler."""
    lang = (lang or config.DEFAULT_LANG)[:2]
    value = STRINGS.get(key)
    if value is None:
        logger.warning("missing string: %s", key)
        return key
    if isinstance(value, dict):
        text = value.get(lang) or value.get("en") or next(iter(value.values()))
    else:
        text = value
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            logger.warning("bad placeholders for %s", key)
            return text
    return text


def lang_name(code: str) -> str:
    return LANGS.get(code[:2], LANGS["en"])


def lang_flag(code: str) -> str:
    return LANG_FLAGS.get(code[:2], "🌐")


def supported(code: str) -> bool:
    return code[:2] in LANGS
