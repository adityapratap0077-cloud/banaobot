"""Static content for the Bhoj House WhatsApp bot.

Bhoj House is a fictional family restaurant in Gorakhpur, UP.
Everything here is bilingual: English + Hindi (Devanagari).
Menu prices are in INR (₹).

This module is pure data — no I/O, no logic.
"""

RESTAURANT = {
    "name": "Bhoj House",
    "tagline_en": "Gorakhpur's favourite family restaurant",
    "tagline_hi": "गोरखपुर का पसंदीदा पारिवारिक रेस्टोरेंट",
    "phone_display": "+91 98765 43210",
    "address_en": "14, Bank Road, Near Golghar, Gorakhpur, Uttar Pradesh 273001",
    "address_hi": "14, बैंक रोड, गोलघर के पास, गोरखपुर, उत्तर प्रदेश 273001",
    "maps_link": "https://maps.google.com/?q=Bank+Road+Golghar+Gorakhpur",
    "hours_open": "11:00",
    "hours_close": "23:00",
    "last_booking": "22:30",
    "delivery_areas": ["Golghar", "Bank Road", "Civil Lines", "Asuran", "Mohaddipur", "Betiahata"],
}

# ---------------------------------------------------------------------------
# Menu: 4 categories, each with items. veg=True -> vegetarian.
# ---------------------------------------------------------------------------
MENU = [
    {
        "id": "starters",
        "name_en": "Starters",
        "name_hi": "स्टार्टर्स",
        "emoji": "🍢",
        "items": [
            {"name_en": "Paneer Tikka", "name_hi": "पनीर टिक्का", "veg": True, "price": 220},
            {"name_en": "Hara Bhara Kebab", "name_hi": "हरा भरा कबाब", "veg": True, "price": 190},
            {"name_en": "Veg Crispy", "name_hi": "वेज क्रिस्पी", "veg": True, "price": 180},
            {"name_en": "Masala Fries", "name_hi": "मसाला फ्राइज़", "veg": True, "price": 120},
            {"name_en": "Chicken Tikka", "name_hi": "चिकन टिक्का", "veg": False, "price": 260},
        ],
    },
    {
        "id": "mains",
        "name_en": "Main Course",
        "name_hi": "मुख्य भोजन",
        "emoji": "🍛",
        "items": [
            {"name_en": "Dal Tadka", "name_hi": "दाल तड़का", "veg": True, "price": 180},
            {"name_en": "Shahi Paneer", "name_hi": "शाही पनीर", "veg": True, "price": 240},
            {"name_en": "Mix Veg", "name_hi": "मिक्स वेज", "veg": True, "price": 210},
            {"name_en": "Veg Biryani", "name_hi": "वेज बिरयानी", "veg": True, "price": 200},
            {"name_en": "Butter Chicken", "name_hi": "बटर चिकन", "veg": False, "price": 320},
            {"name_en": "Chicken Biryani", "name_hi": "चिकन बिरयानी", "veg": False, "price": 280},
        ],
    },
    {
        "id": "breads",
        "name_en": "Breads & Rice",
        "name_hi": "रोटी व चावल",
        "emoji": "🫓",
        "items": [
            {"name_en": "Tandoori Roti", "name_hi": "तंदूरी रोटी", "veg": True, "price": 25},
            {"name_en": "Butter Naan", "name_hi": "बटर नान", "veg": True, "price": 50},
            {"name_en": "Garlic Naan", "name_hi": "गार्लिक नान", "veg": True, "price": 60},
            {"name_en": "Jeera Rice", "name_hi": "जीरा राइस", "veg": True, "price": 150},
            {"name_en": "Veg Fried Rice", "name_hi": "वेज फ्राइड राइस", "veg": True, "price": 170},
        ],
    },
    {
        "id": "beverages",
        "name_en": "Beverages & Desserts",
        "name_hi": "पेय व मिठाई",
        "emoji": "🥤",
        "items": [
            {"name_en": "Sweet Lassi", "name_hi": "मीठी लस्सी", "veg": True, "price": 90},
            {"name_en": "Masala Shikanji", "name_hi": "मसाला शिकंजी", "veg": True, "price": 60},
            {"name_en": "Cold Coffee", "name_hi": "कोल्ड कॉफी", "veg": True, "price": 120},
            {"name_en": "Gulab Jamun (2 pc)", "name_hi": "गुलाब जामुन (2 पीस)", "veg": True, "price": 80},
            {"name_en": "Kulfi Falooda", "name_hi": "कुल्फी फालूदा", "veg": True, "price": 130},
        ],
    },
]

# ---------------------------------------------------------------------------
# FAQs: keyword lists (matched case-insensitively against the raw message).
# ---------------------------------------------------------------------------
FAQS = [
    {
        "id": "delivery",
        "keywords": [
            "deliver", "delivery", "home delivery", "zomato", "swiggy",
            "डिलीवरी", "घर बैठे", "होम डिलीवरी",
        ],
        "answer_en": (
            "🛵 *Home Delivery*\n"
            "Yes! We deliver within ~5 km — Golghar, Bank Road, Civil Lines, "
            "Asuran, Mohaddipur and Betiahata.\n"
            "Order here on WhatsApp, or find us on Zomato & Swiggy.\n"
            "Delivery charge: ₹30 (free above ₹499)."
        ),
        "answer_hi": (
            "🛵 *होम डिलीवरी*\n"
            "जी हाँ! हम लगभग 5 किमी के दायरे में डिलीवरी करते हैं — गोलघर, "
            "बैंक रोड, सिविल लाइंस, असुरन, मोहद्दीपुर और बेतियाहाता।\n"
            "यहीं WhatsApp पर ऑर्डर करें, या Zomato व Swiggy पर हमें खोजें।\n"
            "डिलीवरी शुल्क: ₹30 (₹499 से ऊपर मुफ़्त)।"
        ),
    },
    {
        "id": "parking",
        "keywords": ["parking", "park my", "car park", "पार्किंग", "गाड़ी"],
        "answer_en": (
            "🅿️ *Parking*\n"
            "Yes — we have free parking for cars and two-wheelers right "
            "outside the restaurant on Bank Road."
        ),
        "answer_hi": (
            "🅿️ *पार्किंग*\n"
            "जी हाँ — बैंक रोड पर रेस्टोरेंट के ठीक बाहर कार और दोपहिया "
            "वाहनों के लिए मुफ़्त पार्किंग उपलब्ध है।"
        ),
    },
    {
        "id": "veg",
        "keywords": [
            "veg", "vegetarian", "paneer", "jain", "pure veg",
            "शाकाहारी", "शाकाहार", "जैन", "पनीर",
        ],
        "answer_en": (
            "🥬 *Veg Options*\n"
            "We have a large pure-veg section — paneer, dal, veg biryani, "
            "breads and more. Jain preparations available on request; "
            "just mention it while ordering."
        ),
        "answer_hi": (
            "🥬 *शाकाहारी विकल्प*\n"
            "हमारे पास बड़ा शुद्ध शाकाहारी मेन्यू है — पनीर, दाल, वेज बिरयानी, "
            "रोटी और भी बहुत कुछ। जैन भोजन भी अनुरोध पर उपलब्ध है; "
            "ऑर्डर करते समय बस बता दीजिए।"
        ),
    },
    {
        "id": "payment",
        "keywords": [
            "payment", "pay", "upi", "card", "cash", "gpay", "phonepe",
            "paytm", "bill", "भुगतान", "पैसे", "पेमेंट", "नकद",
        ],
        "answer_en": (
            "💳 *Payment Options*\n"
            "We accept UPI (GPay / PhonePe / Paytm), all major credit & debit "
            "cards, and cash."
        ),
        "answer_hi": (
            "💳 *भुगतान विकल्प*\n"
            "हम UPI (GPay / PhonePe / Paytm), सभी प्रमुख क्रेडिट व डेबिट कार्ड, "
            "और नकद स्वीकार करते हैं।"
        ),
    },
    {
        "id": "spicy",
        "keywords": ["spicy", "mirch", "mirchi", "less spicy", "medium spicy", "तीखा", "मिर्च"],
        "answer_en": (
            "🌶️ *Spice Levels*\n"
            "You can ask for mild, medium or extra spicy while ordering — "
            "our chef adjusts every dish to your taste."
        ),
        "answer_hi": (
            "🌶️ *तीखापन*\n"
            "ऑर्डर करते समय आप हल्का, मध्यम या ज़्यादा तीखा बता सकते हैं — "
            "हमारे शेफ हर डिश आपके स्वाद के अनुसार बनाते हैं।"
        ),
    },
    {
        "id": "banquet",
        "keywords": [
            "banquet", "hall", "birthday", "kitty", "marriage", "shaadi",
            "party of", "bulk", "बैंक्वेट", "हॉल", "शादी", "जन्मदिन", "पार्टी",
        ],
        "answer_en": (
            "🎊 *Parties & Banquets*\n"
            "Yes! Our family hall seats up to 80 guests — birthdays, kitty "
            "parties and small functions. Call us at {phone} and we'll plan "
            "a custom menu for you."
        ).format(phone=RESTAURANT["phone_display"]),
        "answer_hi": (
            "🎊 *पार्टी व बैंक्वेट*\n"
            "जी हाँ! हमारा फैमिली हॉल 80 मेहमानों तक के लिए है — जन्मदिन, किटी "
            "पार्टी और छोटे आयोजन। {phone} पर कॉल कीजिए, हम आपके लिए खास "
            "मेन्यू तैयार करेंगे।"
        ).format(phone=RESTAURANT["phone_display"]),
    },
]

# ---------------------------------------------------------------------------
# UI strings. Every key maps to {"en": ..., "hi": ...}.
# Keep button titles <= 20 characters (WhatsApp limit).
# ---------------------------------------------------------------------------
STR = {
    "welcome": {
        "en": (
            "Hey! Welcome to *Bhoj House* 🙏\n"
            "Gorakhpur's favourite family restaurant.\n\n"
            "Tap below to get started 👇"
        ),
        "hi": (
            "Namaste! *भोज हाउस* mein aapka swagat hai 🙏\n"
            "Gorakhpur ka favourite family restaurant.\n\n"
            "Shuru karne ke liye neeche tap karo 👇"
        ),
    },
    "btn_menu": {"en": "🍽 View Menu", "hi": "🍽 मेन्यू देखें"},
    "btn_book": {"en": "📅 Book a Table", "hi": "📅 टेबल बुक करें"},
    "btn_info": {"en": "📍 Hours & More", "hi": "📍 समय व जानकारी"},
    "btn_confirm": {"en": "✅ Confirm", "hi": "✅ पक्का करें"},
    "btn_cancel": {"en": "❌ Cancel", "hi": "❌ रद्द करें"},
    "btn_back": {"en": "🔙 Back", "hi": "🔙 वापस जाएं"},
    "btn_human": {"en": "🙋 Talk to Human", "hi": "🙋 किसी से बात करें"},
    "hint_human": {
        "en": "_Tip: type 'human' anytime to reach our team._",
        "hi": "_सुझाव: टीम से बात करने के लिए कभी भी 'human' लिखें।_",
    },
    "menu_categories": {
        "en": "Here's our menu 👇\nPick a category:",
        "hi": "यह रहा हमारा मेन्यू 👇\nकोई श्रेणी चुनें:",
    },
    "list_button": {"en": "Browse", "hi": "देखें"},
    "info_list_body": {
        "en": "What would you like to know? 👇",
        "hi": "आप क्या जानना चाहेंगे? 👇",
    },
    "row_hours": {"en": "Hours & Location", "hi": "समय व पता"},
    "row_hours_desc": {"en": "Opening hours, address, map", "hi": "खुलने का समय, पता, नक्शा"},
    "row_delivery": {"en": "Home Delivery", "hi": "होम डिलीवरी"},
    "row_delivery_desc": {"en": "Areas we deliver to", "hi": "डिलीवरी क्षेत्र"},
    "row_veg": {"en": "Veg Options", "hi": "शाकाहारी विकल्प"},
    "row_veg_desc": {"en": "Pure veg & Jain food", "hi": "शुद्ध शाकाहारी व जैन भोजन"},
    "row_payment": {"en": "Payment Options", "hi": "भुगतान विकल्प"},
    "row_payment_desc": {"en": "UPI, cards, cash", "hi": "UPI, कार्ड, नकद"},
    "row_human": {"en": "Talk to Human", "hi": "किसी से बात करें"},
    "row_human_desc": {"en": "Connect to our team", "hi": "हमारी टीम से जुड़ें"},
    "row_lang": {"en": "Switch Language", "hi": "भाषा बदलें"},
    "row_lang_desc": {"en": "English / हिंदी", "hi": "English / हिंदी"},
    "ask_date": {
        "en": "📅 Great! For which *date*?\n_Reply 'today', 'tomorrow' or a date like 25-09._",
        "hi": "📅 बहुत बढ़िया! किस *तारीख* के लिए?\n_'आज', 'कल' या 25-09 जैसी तारीख लिखें।_",
    },
    "bad_date": {
        "en": "Hmm, I couldn't understand that date 😅\nPlease try 'today', 'tomorrow' or DD-MM like 25-09.",
        "hi": "माफ़ कीजिए, तारीख समझ नहीं आई 😅\n'आज', 'कल' या 25-09 जैसा लिखें।",
    },
    "ask_time": {
        "en": "🕗 At what *time*?\n_We're open 11 AM – 11 PM. Reply like '7pm' or '19:30'._",
        "hi": "🕗 किस *समय*?\n_हम सुबह 11 से रात 11 बजे तक खुले हैं। '7pm' या '19:30' जैसा लिखें।_",
    },
    "bad_time": {
        "en": "Sorry, we take bookings between 11:00 AM and 10:30 PM.\nPlease pick a time in that range, e.g. '8pm'.",
        "hi": "माफ़ कीजिए, हम सुबह 11 से रात 10:30 तक बुकिंग लेते हैं।\nइसी बीच का समय चुनें, जैसे '8pm'।",
    },
    "ask_size": {
        "en": "👥 How many *guests*? (1–20)",
        "hi": "👥 कितने *मेहमान* आएँगे? (1–20)",
    },
    "bad_size": {
        "en": "Please tell me the number of guests, between 1 and 20.",
        "hi": "कृपया मेहमानों की संख्या 1 से 20 के बीच बताएँ।",
    },
    "ask_name": {
        "en": "📝 Booking *name*?",
        "hi": "📝 बुकिंग किस *नाम* पर करें?",
    },
    "bad_name": {
        "en": "Please share a name for the booking (at least 2 characters).",
        "hi": "कृपया बुकिंग के लिए नाम बताएँ (कम से कम 2 अक्षर)।",
    },
    "ask_phone": {
        "en": "📱 Your 10-digit *mobile number*?\n_We'll send the confirmation here._",
        "hi": "📱 आपका 10 अंकों का *मोबाइल नंबर*?\n_कन्फर्मेशन इसी पर भेजेंगे।_",
    },
    "bad_phone": {
        "en": "That doesn't look like a valid 10-digit Indian mobile number.\nPlease try again.",
        "hi": "यह सही 10 अंकों का भारतीय मोबाइल नंबर नहीं लग रहा।\nकृपया दोबारा लिखें।",
    },
    "confirm_head": {
        "en": "Please confirm your booking 👇",
        "hi": "कृपया अपनी बुकिंग पक्की करें 👇",
    },
    "booked_ok": {
        "en": (
            "🎉 *Booking confirmed!*\n\n"
            "Your Booking ID is *{bid}*.\n"
            "Please show this ID at the restaurant.\n\n"
            "We can't wait to serve you! 🙏"
        ),
        "hi": (
            "🎉 *बुकिंग पक्की हो गई!*\n\n"
            "आपकी बुकिंग ID *{bid}* है।\n"
            "कृपया रेस्टोरेंट में यह ID दिखाएँ।\n\n"
            "आपकी सेवा में हमें खुशी होगी! 🙏"
        ),
    },
    "cancelled": {
        "en": "No problem — booking cancelled. 👍\nAnything else I can help with? Just say hi!",
        "hi": "कोई बात नहीं — बुकिंग रद्द कर दी गई है। 👍\nक्या मैं किसी और चीज़ में मदद कर सकता हूँ? बस 'hi' लिखें!",
    },
    "cancel_hint": {
        "en": "_Type 'cancel' anytime to stop booking._",
        "hi": "_बुकिंग रोकने के लिए कभी भी 'cancel' लिखें।_",
    },
    "booking_interrupted": {
        "en": "You're in the middle of a booking 🙂\nReply *cancel* to start over, or continue with the booking.",
        "hi": "आप बुकिंग के बीच में हैं 🙂\nदोबारा शुरू करने के लिए *cancel* लिखें, या बुकिंग जारी रखें।",
    },
    "fallback": {
        # NOTE: the engine now rotates friendlier variants from phrasing.py;
        # these are the seeded fallbacks kept for reference.
        "en": (
            "Hmm, didn't quite get that 😅\n"
            "Pick an option below and I'll sort it out."
        ),
        "hi": (
            "Hmm, samajh nahi aaya 😅\n"
            "Neeche options mein se choose kar lo."
        ),
    },
    "handoff": {
        "en": (
            "Connecting you to our team… 🙋\n"
            "Someone will reply here shortly.\n"
            "For urgent help, call us at {phone}."
        ),
        "hi": (
            "आपको हमारी टीम से जोड़ा जा रहा है… 🙋\n"
            "कुछ ही देर में कोई यहाँ जवाब देगा।\n"
            "तुरंत मदद के लिए {phone} पर कॉल करें।"
        ),
    },
    "hours_body": {
        "en": (
            "🕗 *Opening Hours*\n"
            "Monday – Sunday\n"
            "11:00 AM – 11:00 PM\n"
            "_Kitchen closes at 10:30 PM._\n\n"
            "📍 *Address*\n{address}\n\n"
            "🗺 Tap for directions:\n{maps}"
        ),
        "hi": (
            "🕗 *खुलने का समय*\n"
            "सोमवार – रविवार\n"
            "सुबह 11:00 – रात 11:00\n"
            "_रसोई रात 10:30 बजे बंद होती है।_\n\n"
            "📍 *पता*\n{address}\n\n"
            "🗺 रास्ता देखने के लिए दबाएँ:\n{maps}"
        ),
    },
    "lang_set_en": {"en": "✅ Language set to *English*.", "hi": "✅ Language set to *English*."},
    "lang_set_hi": {"en": "✅ भाषा *हिंदी* में बदल गई।", "hi": "✅ भाषा *हिंदी* में बदल गई।"},
    "after_answer": {
        "en": "Anything else? Tap below 👇",
        "hi": "कुछ और? नीचे दबाएँ 👇",
    },
}
