"""Human-voice phrasing packs for BanaoBot.

Every repeated line the engine sends exists here in 2-4 variants, in three
tones (friendly / professional / casual) x two languages (en / hi-Hinglish).
The engine rotates variants with a per-conversation counter, so repeat
visitors don't get identical copy-paste text.

Style rules enforced here:
  * Warm WhatsApp-texting voice: contractions, short bubbles, emoji where
    a real person would use them.
  * NEVER "I am a bot / AI assistant / digital assistant" or anything close.
  * No robotic phrasing ("Please select from the following options",
    "Kindly provide...").
  * Hindi is natural Hinglish as Indians actually text, not textbook Hindi.
  * {name} expands to " <Name>" once the bot learns it, else "".

Variant index 0 of each key is the most "canonical" phrasing — a few legacy
tests assert on substrings of the first variant (e.g. "didn't quite get
that", "cancelled", "Connecting you to our team").
"""

PACKS = {
    # ===================================================================
    "friendly": {
        # ---------------------------------------------------------------
        "en": {
            "greet_nudge": [
                "What are we doing today? 👇",
                "What can I get you? 👇",
                "How can I help? 👇",
            ],
            "enquiry_cancelled": [
                "No worries — enquiry cancelled 👍\nAnything else? Just say hi!",
                "Done{name}, enquiry cancelled 👍",
            ],
            "after_answer": [
                "Anything else{name}? 👇",
                "What else can I do for you{name}? 👇",
                "Anything more{name}? Just tap below 👇",
            ],
            "fallback": [
                "Hmm, didn't quite get that 😅\nPick an option below and I'll sort it out 👇",
                "Arre, that went over my head{name} 😅\nTry one of the buttons below 👇",
                "My bad — I misread that{name} 😅\nTap any option and we'll figure it out 👇",
                "Oops, samajh nahi aaya{name} 😅\nNeeche options hain, wahan se choose kar lo 👇",
            ],
            "handoff": [
                "Connecting you to our team… 🙋\nSomeone will reply here shortly.\n"
                "For anything urgent, call {phone}.",
                "On it{name} — getting someone from our team for you 🙋\n"
                "They'll reply here in a bit. Urgent? Call {phone}.",
                "Let me get a human{name} 🙋\n"
                "Someone from the team will jump in here soon.\n"
                "You can also call {phone}.",
            ],
            "booking_interrupted": [
                "You're in the middle of a booking{name} 🙂\n"
                "Reply *cancel* to start over, or just continue.",
                "Hold on — we were booking{name}! 🙂\n"
                "*cancel* likh do to start over, warna continue karo.",
            ],
            "cancelled": [
                "No worries — booking cancelled 👍\nAnything else? Just say hi!",
                "Done{name}, cancelled 👍\nLet me know if you need anything else!",
                "Cancelled — no problem at all{name} 👍",
            ],
            "ask_date": [
                "When{name}? 📅\nYou can say 'today', 'tomorrow', or a date like 25-09.",
                "Which date{name}? 📅\nTry 'today', 'tomorrow' or 25-09.",
            ],
            "bad_date": [
                "Hmm, that date didn't click 😅\nTry 'today', 'tomorrow' or DD-MM like 25-09.",
                "Samajh nahi aaya{name} 😅\n'date' aise likho — 'today', 'tomorrow' ya 25-09.",
                "That doesn't look like a date I know 😅\n'today', 'tomorrow' ya 25-09 try karo.",
            ],
            "ask_time": [
                "What time{name}? 🕗\nWe're open {open} – {close}. Just say '7pm' or '19:30'.",
                "Time batao{name} 🕗\n{open} se {close} tak khule hain. '7pm' ya '19:30' likh do.",
            ],
            "bad_time": [
                "Hey{name}, we take bookings between {open} and {last} 🙂\n"
                "Pick a time inside that — like '8pm'.",
                "Us time par booking nahi ho payegi{name} 😅\n"
                "{open} se {last} ke beech koi time chuno — jaise '8pm'.",
            ],
            "ask_unit": [
                "How many *{unit}*{name}? (up to {maxp}) 👥",
                "Kitne *{unit}* aayenge{name}? (zyada se zyada {maxp}) 👥",
            ],
            "bad_unit": [
                "Just the number{name} 🙂",
                "Sirf number batao{name} 🙂",
            ],
            "over_capacity": [
                "For *{n} {unit}* I'll need the owner's okay — he'll message you here shortly to sort it out 🙏",
                "That's a big group! *{n} {unit}* needs a quick confirmation from the owner — he'll contact you here soon 👍",
            ],
            "got_datetime": [
                "Got it — *{date}* at *{time}* 👍",
                "Locked in — *{date}*, *{time}* ✅",
            ],
            "got_time_ask_date": [
                "*{time}* noted 👍 — and which *date*? 'today', 'tomorrow' or 25-09.",
                "Okay, *{time}* ⏰ — what date? 'today', 'tomorrow' or 25-09.",
            ],
            "ask_name": [
                "What's the booking name{name}? 📝",
                "Booking kis naam par karoon{name}? 📝",
            ],
            "bad_name": [
                "Need a name with at least 2 letters{name} 😅",
                "Naam thoda lamba likho{name} — kam se kam 2 akshar 😅",
            ],
            "ask_phone": [
                "Your 10-digit mobile number{name}? 📱\nI'll send the confirmation there.",
                "Apna 10-digit mobile number bhejo{name} 📱\nConfirmation wahin aayega.",
            ],
            "bad_phone": [
                "That doesn't look like a valid 10-digit number 😅\nTry again{name}.",
                "Number kuch gadbad lag raha hai{name} 😅\n10-digit sahi number dobara bhejo.",
                "Hmm, ye valid mobile number nahi lag raha 😅\nEk baar phir try karo{name}.",
            ],
            "confirm_head": [
                "Perfect{name} — please confirm 👇",
                "Here's your booking{name}, look good? 👇",
                "Almost done{name}! Just confirm 👇",
            ],
            "enquire_ask_items": [
                "Nice{name}! What would you like to order?\nJust type the item names 👇",
                "Sure{name}! Tell me what you want — e.g. '2 shirts, 1 jeans' 🛍️",
            ],
            "enquire_ok": [
                "Done{name}! I've sent your enquiry to the shop — they'll confirm here shortly. 🙏",
                "Sent{name}! ✅ The shop will reply here soon to confirm your order.",
            ],
        },
        # ---------------------------------------------------------------
        "hi": {
            "greet_nudge": [
                "Aaj kya karna hai? 👇",
                "Batao, kya chahiye? 👇",
                "Kaise madad karoon? 👇",
            ],
            "enquiry_cancelled": [
                "Koi baat nahi — enquiry cancel ho gayi 👍\nAur kuch? Bas hi likh do!",
                "Ho gaya{name}, enquiry cancel 👍",
            ],
            "after_answer": [
                "Aur kuch{name}? 👇",
                "Kuch aur chahiye{name}? Neeche tap karo 👇",
                "Bas? Ya kuch aur{name}? 👇",
            ],
            "fallback": [
                "Hmm, samajh nahi aaya 😅\nNeeche options hain — wahan se choose kar lo 👇",
                "Arre, ye to samajh nahi aaya{name} 😅\nKoi button dabao, solve kar denge 👇",
                "Oops, phir se bolo{name}? 😅\nNeeche diye options try karo 👇",
                "My bad{name}, misread ho gaya 😅\nOptions mein se kuch select karo 👇",
            ],
            "handoff": [
                "Ruko, team se connect karta hoon… 🙋\nKoi jaldi reply karega.\n"
                "Urgent ho to {phone} par call kar lo.",
                "Ek second{name} — team ka koi banda laata hoon 🙋\n"
                "Thodi der mein yahin reply aayega. Urgent? {phone} par call karo.",
                "Insaan se baat karwata hoon{name} 🙋\n"
                "Team jald yahin reply karegi. Ya {phone} par call kar lo.",
            ],
            "booking_interrupted": [
                "Ruko ruko — booking chal rahi hai{name}! 🙂\n"
                "*cancel* likho to start over, warna continue karo.",
                "Are, booking beech mein hai{name} 🙂\nContinue karo ya *cancel* likh do.",
            ],
            "cancelled": [
                "Koi baat nahi — booking cancel ho gayi 👍\nAur kuch? Bas hi likh do!",
                "Ho gaya{name}, cancel kar diya 👍\nKuch aur chahiye to batao!",
                "Cancel ho gaya — bilkul tension nahi{name} 👍",
            ],
            "ask_date": [
                "Kab ka{name}? 📅\n'Today', 'tomorrow' ya 25-09 jaise date likh do.",
                "Kaunsi date{name}? 📅\n'Aaj', 'kal' ya 25-09 try karo.",
            ],
            "bad_date": [
                "Date samajh nahi aayi 😅\n'Aaj', 'kal' ya 25-09 jaise likho.",
                "Ye date to click nahi hui{name} 😅\nPhir se try karo — 'kal' ya 25-09.",
                "Hmm, aisi date nahi samjhi 😅\n'Aaj', 'kal' ya DD-MM format use karo.",
            ],
            "ask_time": [
                "Time batao{name} 🕗\n{open} se {close} tak khule hain. '7pm' ya '19:30' likh do.",
                "Kis time{name}? 🕗\n{open}–{close} open hai. '7pm' jaisa likh do.",
            ],
            "bad_time": [
                "Is time par booking nahi hoti{name} 😅\n{open} se {last} ke beech choose karo — jaise '8pm'.",
                "Hey{name}, {open}–{last} ke beech hi booking hoti hai 🙂\nKoi aur time try karo.",
            ],
            "ask_unit": [
                "Kitne *{unit}* aayenge{name}? (zyada se zyada {maxp}) 👥",
                "Total kitne *{unit}*{name}? (zyada se zyada {maxp}) 👥",
            ],
            "bad_unit": [
                "Sirf number batao{name} 🙂",
                "Number likho{name} 🙂",
            ],
            "over_capacity": [
                "*{n} {unit}* ke liye owner se confirm karna padega — wo yahin message karke arrange kar denge 🙏",
                "Itna bada group! *{n} {unit}* ke liye owner ki permission chahiye — wo jaldi contact karenge 👍",
            ],
            "got_datetime": [
                "Samajh gaya — *{date}* ko *{time}* 👍",
                "Pakka — *{date}*, *{time}* ✅",
            ],
            "got_time_ask_date": [
                "*{time}* note kar liya 👍 — date kaunsi? 'aaj', 'kal' ya 25-09.",
                "Theek hai, *{time}* ⏰ — ab date batao? 'aaj', 'kal' ya 25-09.",
            ],
            "ask_name": [
                "Booking kis naam par karoon{name}? 📝",
                "Naam batao{name} — booking usi par hogi 📝",
            ],
            "bad_name": [
                "Naam kam se kam 2 akshar ka likho{name} 😅",
                "Thoda sahi naam likho{name} 😅",
            ],
            "ask_phone": [
                "Apna 10-digit mobile number bhejo{name} 📱\nConfirmation wahin aayega.",
                "Mobile number{name}? 📱\n10-digit, confirmation ke liye.",
            ],
            "bad_phone": [
                "Ye sahi 10-digit number nahi lag raha 😅\nDobara bhejo{name}.",
                "Number gadbad hai{name} 😅\nSahi 10-digit number likho.",
                "Hmm, valid number nahi laga 😅\nEk baar phir try karo{name}.",
            ],
            "confirm_head": [
                "Perfect{name} — confirm kar do 👇",
                "Ye rahi tumhari booking{name}, sahi hai? 👇",
                "Bas ho gaya{name}! Confirm dabao 👇",
            ],
            "enquire_ask_items": [
                "Badhiya{name}! Kya order karna hai?\nItem ke naam likh do 👇",
                "Haan{name}! Kya chahiye — jaise '2 shirt, 1 jeans' likh do 🛍️",
            ],
            "enquire_ok": [
                "Ho gaya{name}! Enquiry dukaan ko bhej di — jaldi confirm karenge. 🙏",
                "Bhej diya{name}! ✅ Dukaan yahin reply karke confirm karegi.",
            ],
        },
    },
    # ===================================================================
    "professional": {
        "en": {
            "greet_nudge": [
                "How can I help you today? 👇",
                "What can I do for you? 👇",
            ],
            "enquiry_cancelled": [
                "Your enquiry is cancelled{name}. Do let me know if I can help with anything else.",
                "Cancelled{name}, no problem at all 👍",
            ],
            "after_answer": [
                "Anything else I can help with{name}? 👇",
                "Is there anything more{name}? 👇",
            ],
            "fallback": [
                "I didn't quite catch that{name} — could you pick one of the options below? 👇",
                "Apologies, I couldn't follow that{name}. One of the options below will help. 👇",
            ],
            "handoff": [
                "Connecting you to our team…\nSomeone will reply here shortly.\n"
                "For anything urgent, you can call {phone}.",
                "Of course{name} — putting you through to our team.\n"
                "They'll respond here soon. You can also call {phone}.",
            ],
            "booking_interrupted": [
                "You have a booking in progress{name}.\n"
                "Please carry on, or reply *cancel* to start over.",
                "We were partway through your booking{name}.\n"
                "Reply *cancel* to restart, or just continue.",
            ],
            "cancelled": [
                "Your booking is cancelled{name}. Happy to help with anything else.",
                "Cancelled{name}. Feel free to reach out anytime.",
            ],
            "ask_date": [
                "Which date works for you{name}? 📅\nJust say 'today', 'tomorrow', or a date like 25-09.",
                "Your preferred date{name}? 'today', 'tomorrow' or 25-09 works. 📅",
            ],
            "bad_date": [
                "Couldn't recognise that date{name} — try 'today', 'tomorrow' or DD-MM like 25-09.",
                "That date doesn't look right{name}. 'today', 'tomorrow' or 25-09 please.",
            ],
            "ask_time": [
                "And the time{name}? 🕗\nWe're open {open} – {close}. Say '7pm' or '19:30'.",
                "What time suits you{name}? We're here {open} to {close}. 🕗",
            ],
            "bad_time": [
                "We take bookings between {open} and {last}{name}.\n"
                "Any time in that range works, e.g. '8pm'.",
                "That's outside our booking hours{name} ({open} – {last}).\n"
                "Could you pick another time?",
            ],
            "ask_unit": [
                "How many *{unit}*{name}? (up to {maxp})",
                "Number of *{unit}*{name}? (up to {maxp})",
            ],
            "bad_unit": [
                "Just a number{name}, please.",
                "What number works{name}?",
            ],
            "over_capacity": [
                "For *{n} {unit}*, I'll need to confirm with the owner — he'll reach out to you here shortly to arrange it.",
                "A group of *{n} {unit}* needs the owner's confirmation — he'll contact you here soon.",
            ],
            "got_datetime": [
                "Noted — *{date}* at *{time}*.",
                "Confirmed: *{date}*, *{time}*.",
            ],
            "got_time_ask_date": [
                "*{time}* noted — and which date? 'today', 'tomorrow' or 25-09.",
                "Got the time (*{time}*) — which date works? 'today', 'tomorrow' or 25-09.",
            ],
            "ask_name": [
                "The booking name{name}? 📝",
                "Whose name should I book this under{name}? 📝",
            ],
            "bad_name": [
                "Could you share a slightly longer name{name}? At least 2 characters.",
                "That name looks too short{name} — 2 characters minimum.",
            ],
            "ask_phone": [
                "Your 10-digit mobile number{name}? 📱\nThat's where the confirmation goes.",
                "A 10-digit mobile number{name} for the confirmation? 📱",
            ],
            "bad_phone": [
                "That doesn't look like a valid 10-digit number{name} — mind trying again?",
                "Could you double-check that number{name}? It should be 10 digits.",
            ],
            "confirm_head": [
                "Just confirming{name} — does this look right? 👇",
                "One last check{name}: 👇",
            ],
            "enquire_ask_items": [
                "Sure{name}! Which items would you like?\nJust type the names or quantities 👇",
                "Of course{name} — tell me what you'd like, and I'll take it from there 👇",
            ],


            "enquire_ok": [
                "All done{name} — we've received your enquiry and will confirm shortly. ✅",
                "Thank you{name}! Your enquiry is with us — we'll confirm very soon. ✅",
            ],

        },
"hi": {
            "greet_nudge": [
                "Aaj main aapki kya sahayata kar sakta hoon? 👇",
                "Batayein, kya chahiye? 👇",
            ],
            "enquiry_cancelled": [
                "Aapki enquiry cancel kar di gayi hai{name}. Koi aur sahayata chahiye to batayein.",
                "Cancel ho gaya{name}. Kabhi bhi sampark kar sakte hain.",
            ],
            "after_answer": [
                "Kya main aur kuch madad kar sakta hoon{name}? 👇",
                "Kuch aur chahiye{name}? 👇",
            ],
            "fallback": [
                "Maaf kijiye, samajh nahi aaya{name}. Kripya neeche se koi vikalp chunein. 👇",
                "Samajh nahi paaya{name}. Neeche diye gaye options mein se chunein. 👇",
            ],
            "handoff": [
                "Aapko hamari team se jod raha hoon…\nJaldi hi yahan reply aayega.\n"
                "Urgent ho to kripya {phone} par call karein.",
                "Bilkul{name} — team se connect karta hoon.\n"
                "Ve jaldi reply karenge. Ya {phone} par call kar sakte hain.",
            ],
            "booking_interrupted": [
                "Aapki booking chal rahi hai{name}.\nKripya continue karein, ya *cancel* likhein.",
                "Booking beech mein hai{name}.\nContinue karein ya *cancel* likhkar dobara shuru karein.",
            ],
            "cancelled": [
                "Aapki booking cancel kar di gayi hai{name}. Koi aur sahayata chahiye to batayein.",
                "Cancel ho gaya{name}. Kabhi bhi sampark kar sakte hain.",
            ],
            "ask_date": [
                "Kis tareekh ke liye{name}? 📅\n'Aaj', 'kal' ya 25-09 jaise likhein.",
                "Kripya apni date batayein{name} — 'aaj', 'kal' ya 25-09. 📅",
            ],
            "bad_date": [
                "Date samajh nahi aayi{name}. Kripya 'aaj', 'kal' ya 25-09 likhein.",
                "Ye date sahi nahi lag rahi{name}. 'Aaj', 'kal' ya DD-MM use karein.",
            ],
            "ask_time": [
                "Kis samay{name}? 🕗\nHum {open} se {close} tak uplabdh hain. Jaise '7pm' ya '19:30'.",
                "Kripya samay chunein{name} — {open} se {close} tak. 🕗",
            ],
            "bad_time": [
                "Hum {open} se {last} tak hi booking lete hain{name}.\nKripya isi beech ka samay chunein.",
                "Ye samay booking hours ke bahar hai{name} ({open} – {last}). Koi aur samay chunein.",
            ],
            "ask_unit": [
                "Kitne *{unit}*{name}? (adhiktam {maxp})",
                "Kripya *{unit}* ki sankhya batayein{name}? (adhiktam {maxp})",
            ],
            "bad_unit": [
                "Kripya sankhya batayein{name}.",
                "Ek sankhya likhein{name}.",
            ],
            "over_capacity": [
                "*{n} {unit}* ke liye owner se pushti aavashyak hai — ve shighra yahin sampark karke vyavastha karenge.",
                "Itna bada samooh! *{n} {unit}* hetu owner ka anumodan chahiye — ve jaldi sampark karenge.",
            ],
            "got_datetime": [
                "Note kar liya — *{date}* ko *{time}*.",
                "Nischit hua — *{date}*, *{time}*.",
            ],
            "got_time_ask_date": [
                "*{time}* note kiya — kripya date batayein? 'aaj', 'kal' ya 25-09.",
                "Samay (*{time}*) mil gaya — date kaunsi rahegi? 'aaj', 'kal' ya 25-09.",
            ],
            "ask_name": [
                "Booking kis naam par karoon{name}? 📝",
                "Kripya booking ke liye naam batayein{name}. 📝",
            ],
            "bad_name": [
                "Kripya kam se kam 2 aksharon ka naam likhein{name}.",
                "Naam bahut chhota hai{name} — kam se kam 2 akshar.",
            ],
            "ask_phone": [
                "Apna 10-digit mobile number batayein{name}? 📱\nConfirmation wahin bhejenge.",
                "Kripya 10-digit mobile number dein{name} — confirmation ke liye. 📱",
            ],
            "bad_phone": [
                "Ye valid 10-digit mobile number nahi lag raha{name}. Kripya dobara likhein.",
                "Kripya number check karein{name} — 10 digit ka hona chahiye.",
            ],
            "confirm_head": [
                "Kripya booking confirm karein{name} 👇",
                "Neeche details dekhkar confirm karein{name} 👇",
            ],
            "enquire_ask_items": [
                "Zaroor{name}. Kripya un items ke naam likhein jo order karne hain. 👇",
                "Bilkul{name} — kaunse items chahiye? Neeche likh dein. 👇",
            ],
            "enquire_ok": [
                "Dhanyavaad{name}. Aapki enquiry dukaan ko bhej di hai — ve jaldi confirm karenge. 🙏",
                "Note kar liya{name}. Dukaan yahin reply karke order confirm karegi. 🙏",
            ],
        },
    },
    # ===================================================================
    "casual": {
        # ---------------------------------------------------------------
        "en": {
            "greet_nudge": [
                "What's up? 👇",
                "What do you need? 👇",
            ],
            "enquiry_cancelled": [
                "All good — enquiry cancelled{name} 👍\nAnything else? Just say hi!",
                "Cancelled{name}, no stress 👍",
            ],
            "after_answer": [
                "Anything else{name}? 👇",
                "Need anything more{name}? 👇",
            ],
            "fallback": [
                "Haha, didn't quite get that{name} 😅\nHit a button below and we're good 👇",
                "Lost me there{name} 😅\nPick something below 👇",
            ],
            "handoff": [
                "Connecting you to our team… 🙋\nSomeone'll ping you here soon.\n"
                "In a hurry? Call {phone}.",
                "Lemme grab a human{name} 🙋\nThey'll jump in here in a sec. Or call {phone}.",
            ],
            "booking_interrupted": [
                "Yo, we were booking{name}! 😄\nKeep going, or type *cancel* to bail.",
                "We're mid-booking{name} — continue, or *cancel* to restart.",
            ],
            "cancelled": [
                "All good — booking cancelled{name} 👍\nAnything else? Just say hi!",
                "Cancelled{name}, no stress 👍",
            ],
            "ask_date": [
                "When{name}? 📅\n'today', 'tomorrow' or like 25-09.",
                "What date works{name}? 📅",
            ],
            "bad_date": [
                "That date's not clicking{name} 😅\n'today', 'tomorrow' or 25-09?",
                "Nah, didn't get that date{name} 😅\nTry again?",
            ],
            "ask_time": [
                "What time{name}? 🕗\nOpen {open} – {close}. '7pm' works 👌",
                "Time{name}? 🕗\nWe're around {open}–{close}.",
            ],
            "bad_time": [
                "Can't do that time{name} 😅\n{open}–{last} only — '8pm'?",
                "Outta hours{name}! {open} se {last} tak. Another time?",
            ],
            "ask_unit": [
                "How many *{unit}*{name}? (up to {maxp}) 👥",
                "Headcount{name}? *{unit}* — up to {maxp} 👥",
            ],
            "bad_unit": [
                "Just gimme a number{name} 🙂",
                "Number batao{name} 🙂",
            ],
            "over_capacity": [
                "Oho, *{n} {unit}*! That's above what I can book directly — I'll get the owner to confirm, he'll ping you here soon 🙏",
                "Big crew! *{n} {unit}* needs owner approval — he'll hit you up here shortly 👍",
            ],
            "got_datetime": [
                "Bet — *{date}* at *{time}* 👍",
                "Cool, *{date}*, *{time}* ✅",
            ],
            "got_time_ask_date": [
                "*{time}* — got it ⏰ which date? 'today', 'tomorrow' or 25-09.",
                "Time's set (*{time}*) — which date? 'today', 'tomorrow' or 25-09.",
            ],
            "ask_name": [
                "Name for the booking{name}? 📝",
                "Kis naam se{name}? 📝",
            ],
            "bad_name": [
                "Need a real name{name} — 2+ letters 😅",
                "Thoda lamba naam{name} 😅",
            ],
            "ask_phone": [
                "Your number{name}? 📱\n10 digits, confirmation goes there.",
                "Phone number dedo{name} 📱 — 10 digit wala.",
            ],
            "bad_phone": [
                "That number's off{name} 😅\n10 digits, try again?",
                "Nope, not a valid number{name} 😅",
            ],
            "confirm_head": [
                "Look good{name}? Confirm 👇",
                "Sweet — confirm this{name}? 👇",
            ],
            "enquire_ask_items": [
                "Sweet{name}! What do you want?\nDrop the item names 👇",
                "Cool cool{name} — list what you need 🛍️",
            ],
            "enquire_ok": [
                "Sent{name}! ✅ Shop'll confirm here in a bit. 🙏",
                "Done{name}! Enquiry's with the shop now. 🙏",
            ],
        },
        # ---------------------------------------------------------------
        "hi": {
            "greet_nudge": [
                "Kya scene hai? 👇",
                "Bata, kya chahiye? 👇",
            ],
            "enquiry_cancelled": [
                "Chill — enquiry cancel{name} 👍\nAur kuch? Hi likh de!",
                "Cancel done{name}, koi scene nahi 👍",
            ],
            "after_answer": [
                "Aur kuch{name}? 👇",
                "Kuch aur scene hai{name}? 👇",
            ],
            "fallback": [
                "Haha, samajh nahi aaya{name} 😅\nNeeche button dabao 👇",
                "Arre ye kya tha{name}? 😅\nOptions try karo 👇",
            ],
            "handoff": [
                "Ruk, bande ko bulata hoon… 🙋\nYahin reply karega.\nJaldi hai to {phone} par call kar.",
                "Human laata hoon{name} 🙋\n2 min mein reply aayega. Ya {phone} try kar.",
            ],
            "booking_interrupted": [
                "Arey booking chal rahi thi{name}! 😄\nContinue kar ya *cancel* likh.",
                "Beech mein atak gaye{name} — aage badho ya *cancel*.",
            ],
            "cancelled": [
                "Chill — booking cancel{name} 👍\nAur kuch? Hi likh de!",
                "Cancel done{name}, koi scene nahi 👍",
            ],
            "ask_date": [
                "Kab{name}? 📅\n'Aaj', 'kal' ya 25-09.",
                "Date bata{name}? 📅",
            ],
            "bad_date": [
                "Date set nahi hui{name} 😅\n'Aaj', 'kal' ya 25-09?",
                "Nahi samjha date{name} 😅\nPhir se?",
            ],
            "ask_time": [
                "Time{name}? 🕗\n{open}–{close} open hai. '7pm' likh de 👌",
                "Kab aana hai{name}? 🕗",
            ],
            "bad_time": [
                "Is time nahi ho payega{name} 😅\n{open}–{last} tak hi. '8pm'?",
                "Hours ke bahar hai{name}! Koi aur time?",
            ],
            "ask_unit": [
                "Kitne *{unit}*{name}? (zyada se zyada {maxp}) 👥",
                "Headcount{name}? (zyada se zyada {maxp}) 👥",
            ],
            "bad_unit": [
                "Number de{name} 🙂",
                "Bas number{name} 🙂",
            ],
            "over_capacity": [
                "Are wah, *{n} {unit}*! Itna bada group main directly book nahi kar sakta — owner confirm karke yahin message karega 🙏",
                "Bhai *{n} {unit}?! Owner se poochhna padega — wo jaldi ping karega 👍",
            ],
            "got_datetime": [
                "Samajh gaya boss — *{date}* ko *{time}* 👍",
                "Done — *{date}*, *{time}* ✅",
            ],
            "got_time_ask_date": [
                "*{time}* likh liya ⏰ — date bata? 'aaj', 'kal' ya 25-09.",
                "Time set (*{time}*) — ab date? 'aaj', 'kal' ya 25-09.",
            ],
            "ask_name": [
                "Naam{name}? 📝\nBooking usi par hogi.",
                "Kis naam se book karoon{name}? 📝",
            ],
            "bad_name": [
                "Sahi naam likh{name} — 2+ akshar 😅",
                "Naam chhota hai{name} 😅",
            ],
            "ask_phone": [
                "Number{name}? 📱\n10-digit, confirmation ke liye.",
                "Phone de{name} 📱",
            ],
            "bad_phone": [
                "Number galat hai{name} 😅\n10-digit wala phir se bhej.",
                "Valid nahi laga{name} 😅",
            ],
            "confirm_head": [
                "Sahi hai{name}? Confirm kar 👇",
                "Badhiya — confirm{name}? 👇",
            ],
            "enquire_ask_items": [
                "Badhiya{name}! Kya lena hai?\nNaam likh de 👇",
                "Cool{name} — list bana de 🛍️",
            ],
            "enquire_ok": [
                "Bhej diya{name}! ✅ Dukaan confirm karegi yahin. 🙏",
                "Done{name}! Enquiry dukaan ke paas. 🙏",
            ],
        },
    },
}


def pack(tone):
    """Return the tone pack, defaulting to friendly."""
    return PACKS.get(tone) or PACKS["friendly"]


def tones():
    return list(PACKS.keys())
