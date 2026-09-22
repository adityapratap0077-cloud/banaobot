"""Bot templates for BanaoBot — one platform, any business.

Each template parameterizes the *flow labels* so the same rule-based engine
can serve a restaurant, a shop, a freelancer, a clinic, a teacher or a
creator without hardcoding restaurant concepts anywhere.

A template defines:
  catalog / item_plural      nouns used in headings ("Menu", "Products")
  btn_catalog / btn_action    main-menu button titles (<=20 chars, EN+HI)
  booking_enabled             False -> the action button starts an *enquiry*
                              flow (name/phone/items -> owner alert) instead
                              of the date/time booking flow
  unit / unit_word            "guests", "patients", "students" ...
  catalog_heading             category-list heading (EN+HI)
  show_veg                    show the veg/non-veg legend on item lists
  cat_examples / item_example placeholder hints for the catalog builder
  default_tone                friendly | professional | casual
  welcome_en / welcome_hi     default welcome copy ({name}, {tagline})
  booked_ok                   2 confirmation variants per language ({bid},{name})
  hours_note                  hours/location block ({open},{close},{last},
                              {addr},{maps}) — restaurant keeps its legacy
                              "Kitchen closes at" wording
  faq_seeds                   starter FAQs seeded at business creation

Pure data — no I/O. storage.py copies the overridable bits (button labels,
unit, welcome, booking on/off, tone default) into each business row so the
owner can tweak them in Settings; engine.py reads the merged bundle.
"""

from content import FAQS as _RESTAURANT_FAQS

TEMPLATES = {
    "restaurant": {
        "name": "Restaurant",
        "emoji": "🍽️",
        "blurb": "Restaurants, cafes, dhabas, bakeries, cloud kitchens",
        "catalog": {"en": "Menu", "hi": "मेन्यू"},
        "item_plural": {"en": "items", "hi": "items"},
        "btn_catalog": {"en": "🍽 View Menu", "hi": "🍽 मेन्यू देखें"},
        "booking_enabled": True,
        "btn_action": {"en": "📅 Book a Table", "hi": "📅 टेबल बुक करें"},
        "unit": {"en": "guests", "hi": "मेहमान"},
        "unit_word": {"en": "Guests", "hi": "मेहमान"},
        "catalog_heading": {
            "en": "Here's our menu 👇\nPick a category:",
            "hi": "यह रहा हमारा मेन्यू 👇\nकोई श्रेणी चुनें:",
        },
        "show_veg": True,
        "cat_examples": "e.g. Starters, Main Course, Desserts",
        "item_example": "e.g. Paneer Tikka",
        "default_tone": "friendly",
        "welcome_en": (
            "Hey! Welcome to *{name}* 🙏\n{tagline}\n\nTap below to get started 👇"
        ),
        "welcome_hi": (
            "Namaste! *{name}* mein aapka swagat hai 🙏\n{tagline}\n\n"
            "Shuru karne ke liye neeche tap karo 👇"
        ),
        "booked_ok": {
            "en": [
                "🎉 *Booking confirmed!*\n\n"
                "Your Booking ID is *{bid}*.\n"
                "Please show this ID at the restaurant.\n\n"
                "We can't wait to serve you! 🙏",
                "Done! 🎉 Your table's booked{name}.\n"
                "Booking ID: *{bid}* — just show it when you arrive.\n"
                "See you soon! 🙏",
            ],
            "hi": [
                "🎉 *बुकिंग पक्की हो गई!*\n\n"
                "आपकी बुकिंग ID *{bid}* है।\n"
                "कृपया रेस्टोरेंट में यह ID दिखाएँ।\n\n"
                "आपकी सेवा में हमें खुशी होगी! 🙏",
                "Ho gaya! 🎉 Table book ho gayi{name}.\n"
                "Booking ID: *{bid}* — aate time dikha dena.\n"
                "Milte hain! 🙏",
            ],
        },
        "hours_note": {
            "en": ("🕗 *Opening Hours*\nMonday – Sunday\n{open} – {close}\n"
                   "_Kitchen closes at {last}._\n\n"
                   "📍 *Address*\n{addr}\n\n🗺 Tap for directions:\n{maps}"),
            "hi": ("🕗 *खुलने का समय*\nसोमवार – रविवार\n{open} – {close}\n"
                   "_रसोई {last} बजे बंद होती है।_\n\n"
                   "📍 *पता*\n{addr}\n\n🗺 रास्ता देखने के लिए दबाएँ:\n{maps}"),
        },
        "faq_seeds": [
            {
                "id": f["id"],
                "keywords": f["keywords"],
                "answer_en": f["answer_en"],
                "answer_hi": f["answer_hi"],
            }
            for f in _RESTAURANT_FAQS
        ],
    },
    "shop": {
        "name": "Shop",
        "emoji": "🛍️",
        "blurb": "Clothing, electronics, kirana, gifts — anything you sell",
        "catalog": {"en": "Products", "hi": "प्रोडक्ट्स"},
        "item_plural": {"en": "products", "hi": "products"},
        "btn_catalog": {"en": "🛍 Browse Products", "hi": "🛍 प्रोडक्ट देखें"},
        "booking_enabled": False,
        "btn_action": {"en": "🛒 Enquire to Order", "hi": "🛒 ऑर्डर करें"},
        "unit": {"en": "people", "hi": "लोग"},
        "unit_word": {"en": "People", "hi": "लोग"},
        "catalog_heading": {
            "en": "Here's our collection 👇\nPick a category:",
            "hi": "Yeh raha hamara collection 👇\nKoi category chuno:",
        },
        "show_veg": False,
        "cat_examples": "e.g. Men, Women, New Arrivals",
        "item_example": "e.g. Blue Denim Shirt",
        "default_tone": "friendly",
        "welcome_en": (
            "Hey! Welcome to *{name}* 🛍️\n{tagline}\n\nBrowse the collection below 👇"
        ),
        "welcome_hi": (
            "Namaste! *{name}* mein swagat hai 🛍️\n{tagline}\n\n"
            "Neeche collection dekho 👇"
        ),
        "booked_ok": {
            "en": ["Order noted{name}! ✅\nReference: *{bid}*\nWe'll confirm shortly. 🙏"],
            "hi": ["Order note ho gaya{name}! ✅\nReference: *{bid}*\nJaldi confirm karte hain. 🙏"],
        },
        "hours_note": {
            "en": ("🕗 *Store Hours*\nMonday – Sunday\n{open} – {close}\n\n"
                   "📍 *Address*\n{addr}\n\n🗺 Directions:\n{maps}"),
            "hi": ("🕗 *दुकान का समय*\nसोमवार – रविवार\n{open} – {close}\n\n"
                   "📍 *पता*\n{addr}\n\n🗺 रास्ता:\n{maps}"),
        },
        "faq_seeds": [
            {
                "id": "shipping",
                "keywords": ["deliver", "delivery", "shipping", "ship", "डिलीवरी", "भेज"],
                "answer_en": ("📦 *Delivery*\nYes, we deliver! Local delivery is same-day; "
                              "shipping across India takes 3–5 days. Charges depend on your area — "
                              "just share your pincode and I'll tell you. 🙂"),
                "answer_hi": ("📦 *डिलीवरी*\nHaan, hum deliver karte hain! Local same-day; "
                              "poore India mein 3–5 din lagte hain. Apna pincode bhejo, "
                              "charges bata deta hoon. 🙂"),
            },
            {
                "id": "payment",
                "keywords": ["payment", "pay", "upi", "card", "cash", "cod", "पेमेंट", "पैसे"],
                "answer_en": ("💳 *Payment*\nWe take UPI, cards, and cash. "
                              "COD is available on local orders. 🙂"),
                "answer_hi": ("💳 *पेमेंट*\nHum UPI, card aur cash lete hain. "
                              "Local orders par COD bhi hai. 🙂"),
            },
            {
                "id": "returns",
                "keywords": ["return", "exchange", "refund", "वापस", "बदल"],
                "answer_en": ("↩️ *Returns & Exchange*\nUnused items can be exchanged within 7 days — "
                              "just keep the bill. For anything damaged, send us a photo here and "
                              "we'll sort it out. 👍"),
                "answer_hi": ("↩️ *रिटर्न व एक्सचेंज*\n7 din ke andar unused items exchange ho jayenge — "
                              "bill sambhaal ke rakhna. Kuch damaged aaye to yahin photo bhej do, "
                              "solve kar denge. 👍"),
            },
        ],
    },
    "freelancer": {
        "name": "Freelancer / Services",
        "emoji": "💼",
        "blurb": "Designers, developers, photographers, salons, repair",
        "catalog": {"en": "Services", "hi": "सर्विसेज़"},
        "item_plural": {"en": "services", "hi": "services"},
        "btn_catalog": {"en": "💼 View Services", "hi": "💼 सर्विस देखें"},
        "booking_enabled": True,
        "btn_action": {"en": "📅 Book a Call", "hi": "📅 कॉल बुक करें"},
        "unit": {"en": "people", "hi": "लोग"},
        "unit_word": {"en": "People", "hi": "लोग"},
        "catalog_heading": {
            "en": "Here's what I do 👇\nPick a category:",
            "hi": "Main ye sab karta hoon 👇\nKoi category chuno:",
        },
        "show_veg": False,
        "cat_examples": "e.g. Design, Development, Packages",
        "item_example": "e.g. Logo Design",
        "default_tone": "professional",
        "welcome_en": (
            "Hey, I'm *{name}* 💼\n{tagline}\n\nHere's what I do — tap below 👇"
        ),
        "welcome_hi": (
            "Hey! Main hoon *{name}* 💼\n{tagline}\n\nDekho main kya karta hoon 👇"
        ),
        "booked_ok": {
            "en": [
                "You're booked{name}! 🎉\nBooking ID: *{bid}*\n"
                "I'll confirm the call details here shortly. 👍",
                "Done{name} — call scheduled! 🎉\nBooking ID: *{bid}*\n"
                "Talk soon. 👍",
            ],
            "hi": [
                "Book ho gaya{name}! 🎉\nBooking ID: *{bid}*\n"
                "Call ki details yahin confirm kar dunga. 👍",
                "Ho gaya{name} — call scheduled! 🎉\nBooking ID: *{bid}*\n"
                "Jaldi baat karte hain. 👍",
            ],
        },
        "hours_note": {
            "en": ("🕗 *Working Hours*\nMonday – Saturday\n{open} – {close}\n\n"
                   "📍 *Address*\n{addr}\n\n🗺 Directions:\n{maps}"),
            "hi": ("🕗 *काम का समय*\nसोमवार – शनिवार\n{open} – {close}\n\n"
                   "📍 *पता*\n{addr}\n\n🗺 रास्ता:\n{maps}"),
        },
        "faq_seeds": [
            {
                "id": "pricing",
                "keywords": ["price", "pricing", "cost", "charge", "rate", "fees", "कीमत", "दाम", "रेट"],
                "answer_en": ("💰 *Pricing*\nEvery project is a little different, so I quote after a quick "
                              "chat about what you need. Tap 'Book a Call' and I'll give you a clear "
                              "number — no hidden charges. 🙂"),
                "answer_hi": ("💰 *प्राइसिंग*\nHar project thoda alag hota hai, isliye quote ek chhoti "
                              "baat ke baad deta hoon. 'Book a Call' dabao — saaf-saaf number dunga, "
                              "koi hidden charges nahi. 🙂"),
            },
            {
                "id": "process",
                "keywords": ["process", "how", "work", "steps", "procedure", "कैसे", "प्रोसेस"],
                "answer_en": ("⚙️ *How it works*\n1. We chat about what you need.\n"
                              "2. You get a fixed quote + timeline.\n"
                              "3. I start once you approve — with updates at every step. 👍"),
                "answer_hi": ("⚙️ *कैसे काम करता हूँ*\n1. Pehle baat karte hain — chahiye kya.\n"
                              "2. Fixed quote + timeline milta hai.\n"
                              "3. Approval ke baad kaam shuru — har step par update. 👍"),
            },
            {
                "id": "availability",
                "keywords": ["available", "availability", "when", "slot", "busy", "खाली", "समय"],
                "answer_en": ("📅 *Availability*\nI usually have slots within a week. "
                              "Book a call and we'll lock a time that suits you. 🙂"),
                "answer_hi": ("📅 *उपलब्धता*\nAam taur par ek hafte ke andar slot mil jaata hai. "
                              "Call book karo, time fix kar lete hain. 🙂"),
            },
        ],
    },
    "clinic": {
        "name": "Clinic",
        "emoji": "🏥",
        "blurb": "Doctors, dentists, physios, labs, wellness",
        "catalog": {"en": "Treatments", "hi": "इलाज"},
        "item_plural": {"en": "treatments", "hi": "treatments"},
        "btn_catalog": {"en": "🏥 View Treatments", "hi": "🏥 इलाज देखें"},
        "booking_enabled": True,
        "btn_action": {"en": "📅 Book Appointment", "hi": "📅 अपॉइंटमेंट लें"},
        "unit": {"en": "patients", "hi": "मरीज़"},
        "unit_word": {"en": "Patients", "hi": "मरीज़"},
        "catalog_heading": {
            "en": "Our treatments & services 👇\nPick a category:",
            "hi": "Hamare treatments 👇\nKoi category chunein:",
        },
        "show_veg": False,
        "cat_examples": "e.g. General, Dental, Diagnostics",
        "item_example": "e.g. General Consultation",
        "default_tone": "professional",
        "welcome_en": (
            "Welcome to *{name}* 🏥\n{tagline}\n\nHow can we help you today? 👇"
        ),
        "welcome_hi": (
            "*{name}* mein aapka swagat hai 🏥\n{tagline}\n\nAaj hum aapki kya madad kar sakte hain? 👇"
        ),
        "booked_ok": {
            "en": [
                "Appointment confirmed{name}. 🏥\nBooking ID: *{bid}*\n"
                "Please arrive 10 minutes early. 🙏",
                "Done{name} — your visit is scheduled. 🏥\nBooking ID: *{bid}*\n"
                "Please carry any previous reports. 🙏",
            ],
            "hi": [
                "Appointment confirm ho gaya{name}. 🏥\nBooking ID: *{bid}*\n"
                "Kripya 10 minute pehle pahunchein. 🙏",
                "Ho gaya{name} — visit scheduled. 🏥\nBooking ID: *{bid}*\n"
                "Purani reports saath le aayein. 🙏",
            ],
        },
        "hours_note": {
            "en": ("🕗 *Clinic Hours*\nMonday – Saturday\n{open} – {close}\n"
                   "_Last appointment at {last}._\n\n"
                   "📍 *Address*\n{addr}\n\n🗺 Directions:\n{maps}"),
            "hi": ("🕗 *क्लिनिक का समय*\nसोमवार – शनिवार\n{open} – {close}\n"
                   "_आखिरी अपॉइंटमेंट {last} बजे।_\n\n"
                   "📍 *पता*\n{addr}\n\n🗺 रास्ता:\n{maps}"),
        },
        "faq_seeds": [
            {
                "id": "timings",
                "keywords": ["timing", "hours", "open", "close", "समय", "खुला"],
                "answer_en": ("🕗 *Timings*\nWe take appointments through this chat — tap 'Book Appointment'. "
                              "For anything urgent, please call us directly. 🏥"),
                "answer_hi": ("🕗 *समय*\nAppointment isi chat se book hota hai — 'Book Appointment' dabayein. "
                              "Urgent ho to please call kar lein. 🏥"),
            },
            {
                "id": "first_visit",
                "keywords": ["first", "visit", "new patient", "पहली बार"],
                "answer_en": ("🩺 *First Visit*\nPlease arrive 10 minutes early and carry any previous "
                              "prescriptions or reports. New patients are always welcome. 🙂"),
                "answer_hi": ("🩺 *पहली विज़िट*\nKripya 10 minute pehle aayein aur purane prescription ya "
                              "reports saath laayein. Naye patients ka swagat hai. 🙂"),
            },
            {
                "id": "reports",
                "keywords": ["report", "test", "lab", "blood", "रिपोर्ट", "जांच"],
                "answer_en": ("🧪 *Tests & Reports*\nReports are usually ready within 24 hours and shared "
                              "on WhatsApp. Ask us here if you need one urgently. 🙂"),
                "answer_hi": ("🧪 *टेस्ट व रिपोर्ट*\nReports aam taur par 24 ghante mein taiyaar ho jaati hain "
                              "aur WhatsApp par bhej di jaati hain. Urgent ho to yahin pooch lein. 🙂"),
            },
        ],
    },
    "teacher": {
        "name": "Teacher / Coaching",
        "emoji": "🎓",
        "blurb": "Tutors, music/dance teachers, coaching institutes",
        "catalog": {"en": "Courses", "hi": "कोर्सेज़"},
        "item_plural": {"en": "courses", "hi": "courses"},
        "btn_catalog": {"en": "🎓 View Courses", "hi": "🎓 कोर्स देखें"},
        "booking_enabled": True,
        "btn_action": {"en": "🎓 Book Free Demo", "hi": "🎓 फ्री डेमो बुक करें"},
        "unit": {"en": "students", "hi": "छात्र"},
        "unit_word": {"en": "Students", "hi": "छात्र"},
        "catalog_heading": {
            "en": "Our courses 👇\nPick a category:",
            "hi": "Hamare courses 👇\nKoi category chuno:",
        },
        "show_veg": False,
        "cat_examples": "e.g. Beginner, Intermediate, Advanced",
        "item_example": "e.g. Guitar Basics (8 weeks)",
        "default_tone": "friendly",
        "welcome_en": (
            "Hey! Welcome to *{name}* 🎓\n{tagline}\n\nTap below to explore courses or book a free demo 👇"
        ),
        "welcome_hi": (
            "Hey! *{name}* mein swagat hai 🎓\n{tagline}\n\nCourse dekho ya free demo book karo 👇"
        ),
        "booked_ok": {
            "en": [
                "Demo class booked{name}! 🎓\nBooking ID: *{bid}*\n"
                "We'll share the class link here before it starts. 🙏",
                "You're in{name}! 🎓\nBooking ID: *{bid}*\n"
                "Demo details are on their way — see you in class! 🙏",
            ],
            "hi": [
                "Demo class book ho gayi{name}! 🎓\nBooking ID: *{bid}*\n"
                "Class ka link yahin bhej denge. 🙏",
                "Ho gaya{name}! 🎓\nBooking ID: *{bid}*\n"
                "Demo ki details bhej rahe hain — class mein milte hain! 🙏",
            ],
        },
        "hours_note": {
            "en": ("🕗 *Class Hours*\nMonday – Sunday\n{open} – {close}\n"
                   "_Last demo slot at {last}._\n\n"
                   "📍 *Address*\n{addr}\n\n🗺 Directions:\n{maps}"),
            "hi": ("🕗 *क्लास का समय*\nसोमवार – रविवार\n{open} – {close}\n"
                   "_आखिरी डेमो स्लॉट {last} बजे।_\n\n"
                   "📍 *पता*\n{addr}\n\n🗺 रास्ता:\n{maps}"),
        },
        "faq_seeds": [
            {
                "id": "demo",
                "keywords": ["demo", "trial", "free class", "डेमो", "ट्रायल"],
                "answer_en": ("🎓 *Free Demo*\nYes! Your first demo class is completely free — no card, "
                              "no commitment. Tap 'Book Free Demo' and pick a time. 🙂"),
                "answer_hi": ("🎓 *फ्री डेमो*\nHaan! Pehli demo class bilkul free hai — koi card nahi, "
                              "koi commitment nahi. 'Book Free Demo' dabao aur time chuno. 🙂"),
            },
            {
                "id": "fees",
                "keywords": ["fee", "fees", "price", "cost", "charge", "फीस", "कीमत"],
                "answer_en": ("💰 *Fees*\nFees depend on the course — each course card shows its price. "
                              "We also have easy monthly plans. Ask here if you want details. 🙂"),
                "answer_hi": ("💰 *फीस*\nFees course par depend karti hai — har course card par price likha hai. "
                              "Monthly plans bhi hain. Details chahiye to yahin pooch lo. 🙂"),
            },
            {
                "id": "mode",
                "keywords": ["online", "offline", "mode", "zoom", "ऑनलाइन", "ऑफलाइन"],
                "answer_en": ("💻 *Online / Offline*\nWe do both! Online classes run live with small batches; "
                              "offline batches run at our center. Pick what suits you when you book. 🙂"),
                "answer_hi": ("💻 *ऑनलाइन / ऑफलाइन*\nDono hota hai! Online classes live hoti hain, chhote batches "
                              "mein; offline batches hamare center par. Book karte time choose kar lo. 🙂"),
            },
        ],
    },
    "creator": {
        "name": "Creator / Personal",
        "emoji": "✨",
        "blurb": "YouTubers, coaches, artists — your personal brand bot",
        "catalog": {"en": "Offerings", "hi": "ऑफरिंग्स"},
        "item_plural": {"en": "items", "hi": "items"},
        "btn_catalog": {"en": "✨ View Offerings", "hi": "✨ ऑफरिंग देखें"},
        "booking_enabled": True,
        "btn_action": {"en": "📅 Book a Call", "hi": "📅 कॉल बुक करें"},
        "unit": {"en": "attendees", "hi": "प्रतिभागी"},
        "unit_word": {"en": "Attendees", "hi": "प्रतिभागी"},
        "catalog_heading": {
            "en": "Here's what I've got 👇\nPick a category:",
            "hi": "Dekho mere paas kya hai 👇\nKoi category chuno:",
        },
        "show_veg": False,
        "cat_examples": "e.g. 1:1 Calls, Workshops, Content",
        "item_example": "e.g. 30-min 1:1 Call",
        "default_tone": "casual",
        "welcome_en": (
            "Hey! *{name}* here ✨\n{tagline}\n\nCheck out what I've got 👇"
        ),
        "welcome_hi": (
            "Hey! *{name}* here ✨\n{tagline}\n\nDekho mere paas kya hai 👇"
        ),
        "booked_ok": {
            "en": [
                "Locked in{name}! ✨\nBooking ID: *{bid}*\nTalk soon! 🙏",
                "Done deal{name}! ✨\nBooking ID: *{bid}*\nCatch you then! 🙏",
            ],
            "hi": [
                "Lock ho gaya{name}! ✨\nBooking ID: *{bid}*\nJaldi baat karte hain! 🙏",
                "Ho gaya{name}! ✨\nBooking ID: *{bid}*\nMilte hain! 🙏",
            ],
        },
        "hours_note": {
            "en": ("🕗 *Available*\nMonday – Sunday\n{open} – {close}\n\n"
                   "📍 *Based in*\n{addr}"),
            "hi": ("🕗 *उपलब्ध*\nसोमवार – रविवार\n{open} – {close}\n\n"
                   "📍 *पता*\n{addr}"),
        },
        "faq_seeds": [
            {
                "id": "collab",
                "keywords": ["collab", "collaboration", "sponsor", "brand", "partner"],
                "answer_en": ("🤝 *Collabs*\nI do! Share your brand + idea here and I'll get back with "
                              "rates and timelines. For anything urgent, tap 'Book a Call'. ✨"),
                "answer_hi": ("🤝 *कोलैब*\nHaan, karta hoon! Apna brand + idea yahin bhejo, "
                              "rates aur timeline bata dunga. Urgent ho to 'Book a Call' dabao. ✨"),
            },
            {
                "id": "pricing",
                "keywords": ["price", "pricing", "cost", "charge", "rate", "fees", "कीमत"],
                "answer_en": ("💰 *Pricing*\nEverything's listed under Offerings with clear prices — "
                              "no DMs asking 'price pls'. 😄 Tap below to browse."),
                "answer_hi": ("💰 *प्राइसिंग*\nSab kuch Offerings mein saaf price ke saath hai — "
                              "'price pls' wale DM ki zaroorat nahi. 😄 Neeche dekho."),
            },
            {
                "id": "contact",
                "keywords": ["contact", "email", "reach", "dm", "संपर्क"],
                "answer_en": ("📩 *Contact*\nFastest way is right here on WhatsApp! For longer stuff, "
                              "book a call and we'll talk properly. ✨"),
                "answer_hi": ("📩 *संपर्क*\nSabse fast yahin WhatsApp par! Lambi baat ke liye "
                              "call book kar lo. ✨"),
            },
        ],
    },
}

TEMPLATE_IDS = tuple(TEMPLATES.keys())


def get(tid):
    """Return the template dict for tid, falling back to restaurant."""
    return TEMPLATES.get(tid) or TEMPLATES["restaurant"]


def ids():
    return list(TEMPLATES.keys())


def render_welcome(tid, name, tagline_en="", tagline_hi="", lang="en"):
    """Build the default welcome message for a new business."""
    tpl = get(tid)
    key = "welcome_hi" if lang == "hi" else "welcome_en"
    tagline = tagline_hi if lang == "hi" else tagline_en
    text = tpl[key].format(name=name, tagline=tagline or "")
    # collapse blank lines left by an empty tagline
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text.replace("\n\n\n", "\n\n")
