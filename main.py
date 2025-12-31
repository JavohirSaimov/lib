import os
import asyncio
import logging
import base64
import json
import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder


# --- KONFIGURATSIYA ---
# Yangi API token o'rnatildi
API_TOKEN = '8455171223:AAHyWiE3It1y8w5MmUZ00fkyWA9PDvdlHKI'
# Gemini API kalitingiz
GEMINI_API_KEY = "AIzaSyDCbZmtZn8P12lJcwyrcMT2-0HE4gTv1Qg"

# Logging sozlamalari
logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# --- GEMINI AI CORE FUNCTIONS ---

async def call_gemini(prompt, image_base64=None):
    # Barqaror model manzili
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"

    parts = [{"text": prompt}]
    if image_base64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": image_base64}})

    # MUHIM: generationConfig olib tashlandi, chunki u oddiy matn uchun xalaqit beradi
    payload = {
        "contents": [{"parts": parts}]
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, timeout=15) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['candidates'][0]['content']['parts'][0]['text']
                else:
                    error_data = await response.text()
                    logging.error(f"Gemini API Error: {response.status} - {error_data}")
                    return None
        except Exception as e:
            logging.error(f"Network error: {e}")
            return None

async def get_kanji_variants(image_base64):
    """Rasmni tahlil qilib, so'z yoki iyeroglif variantlarini JSONda qaytaradi."""
    prompt = (
        "Siz yapon tili OCR mutaxassisiz. Rasmdagi yaponcha so'z yoki iborani to'liq aniqlang. "
        "Agar rasmda qo'shma so'z (bir nechta kanji) bo'lsa, ularni birga (bitta so'z sifatida) bering. "
        "Agar rasm xira bo'lsa, eng yaqin 4 ta variantni bering. "
        "Javobni FAQAT ushbu JSON formatida bering: "
        '{"variants": [{"kanji": "...", "reading": "...", "meaning": "..."}]}'
    )
    res = await call_gemini(prompt, image_base64)
    try:
        if not res: return None
        # JSONni tozalash
        text_data = res.strip()
        if "```json" in text_data:
            text_data = text_data.split("```json")[1].split("```")[0].strip()
        elif "```" in text_data:
            text_data = text_data.split("```")[1].split("```")[0].strip()

        return json.loads(text_data)
    except Exception as e:
        logging.error(f"JSON Parse Error: {e}\nResponse: {res}")
        return None

# --- BOT HANDLERS ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Bot ishga tushgandagi kutib olish xabari."""
    await message.answer(
        "🎎 <b>Kon'nichiwa!</b>\n\nMen yapon tili bo'yicha aqlli yordamchingizman.\n\n"
        "1️⃣ Menga iyeroglifli <b>rasm</b> yuboring.\n"
        "2️⃣ Yoki iyerogliflarni to'g'ridan-to'g'ri <b>yozib yuboring</b>.\n\n"
        "Men sizga ularning yozilish tartibini (GIF) va misollarni taqdim etaman! 🌸",
        parse_mode='HTML'
    )

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    """Rasmni yuklab oladi va Gemini'dan variantlarni so'raydi."""
    processing = await message.answer("🧐 <b>Tahlil ketyapti...</b> 🏮", parse_mode='HTML')

    try:
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        file_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_info.file_path}"

        async with aiohttp.ClientSession() as session:
            async with session.get(file_url) as resp:
                if resp.status != 200:
                    await processing.edit_text("❌ Rasmni yuklab bo'lmadi.")
                    return

                image_bytes = await resp.read()
                image_base64 = base64.b64encode(image_bytes).decode('utf-8')

                # Variantlarni AI orqali olish
                data = await get_kanji_variants(image_base64)

                if not data or 'variants' not in data or not data['variants']:
                    await processing.edit_text("🏮 Kechirasiz, matn topilmadi. Yaxshiroq rasm yuboring.")
                    return

                await processing.delete()

                # Variantlar klaviaturasini yasash
                builder = InlineKeyboardBuilder()
                text_msg = "🤔 <b>Men quyidagi variantlarni topdim. Qaysi biri rasmga mos?</b>\n\n"

                for v in data['variants']:
                    text_msg += f"🔹 <b>{v['kanji']}</b> ({v['reading']}) - {v['meaning']}\n"
                    builder.button(text=f"{v['kanji']}", callback_data=f"sel_{v['kanji']}")

                builder.adjust(2)
                await message.answer(text_msg, reply_markup=builder.as_markup(), parse_mode='HTML')

    except Exception as e:
        logging.exception("Error in handle_photo")
        await message.answer("⚠️ Xatolik yuz berdi. Iltimos, qaytadan urinib ko'ring.")

@dp.message(F.text & ~F.status_updates)
async def handle_text_kanji(message: types.Message):
    """Foydalanuvchi matn sifatida kanji yuborganda ishlaydi."""
    word = message.text.strip()
    if not word: return

    # Faqat tanlash tugmachasini yuboramiz (xuddi rasm tahlilidan keyingidek)
    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Yozish tartibi", callback_data=f"str_{word}")

    builder.adjust(1)

    await message.answer(
        f"✅ <b>Qabul qilindi: {word}</b>\n\nNima qilishni xohlaysiz? 👇",
        reply_markup=builder.as_markup(),
        parse_mode='HTML'
    )

@dp.callback_query(F.data.startswith("sel_"))
async def on_kanji_selected(callback: types.CallbackQuery):
    """Variant tanlanganda tugmalarni ko'rsatadi (Talaffuz olib tashlandi)."""
    kanji = callback.data.split("_")[1]
    await callback.answer(f"Tanlandi: {kanji}")

    builder = InlineKeyboardBuilder()
    builder.button(text="✍️ Yozish tartibi", callback_data=f"str_{kanji}")
    builder.button(text="📖 Ko'p misollar", callback_data=f"exm_{kanji}")
    builder.adjust(1)

    await callback.message.answer(
        f"✅ <b>Tasdiqlandi: {kanji}</b>\n\nUshbu so'z haqida qanday ma'lumot kerak? 👇",
        reply_markup=builder.as_markup(),
        parse_mode='HTML'
    )

# --- CALLBACK LOGIC ---

@dp.callback_query(F.data.startswith("str_"))
async def callback_stroke_order(callback: types.CallbackQuery):
    """
    So'zdagi HAR BIR iyeroglif uchun alohida GIF yuklab olib, ketma-ket yuborish.
    """
    word = callback.data.split("_")[1]
    await callback.answer(f"Animatsiyalar yuklanmoqda...")

    found_count = 0

    async with aiohttp.ClientSession() as session:
        for char in word:
            try:
                char_hex_short = hex(ord(char))[2:].lower()
                char_hex_long = char_hex_short.zfill(5)

                sources = [
                    (f"https://raw.githubusercontent.com/mistval/kanji_images/master/gifs/{char_hex_long}.gif", "gif"),
                    (f"https://raw.githubusercontent.com/mistval/kanji_images/master/gifs/{char_hex_short}.gif", "gif"),
                    (f"https://kanji.jisho.org/static/images/stroke_diagrams/{ord(char)}_frames.png", "png")
                ]

                file_sent = False
                for url, file_type in sources:
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                file_data = await resp.read()
                                input_file = types.BufferedInputFile(file_data, filename=f"{char}.{file_type}")

                                caption_text = f"✍️ <b>{char}</b>"

                                if file_type == "gif":
                                    await callback.message.answer_animation(
                                        animation=input_file,
                                        caption=caption_text, parse_mode='HTML'
                                    )
                                else:
                                    await callback.message.answer_photo(
                                        photo=input_file,
                                        caption=caption_text + " (Diagramma)", parse_mode='HTML'
                                    )

                                file_sent = True
                                found_count += 1
                                await asyncio.sleep(0.3)
                                break
                    except Exception:
                        continue
            except Exception as e:
                logging.error(f"Error processing char {char}: {e}")

    if found_count == 0:
        await callback.message.answer("⚠️ Kechirasiz, bu so'z uchun animatsiyalar topilmadi.")
    else:
        await callback.message.answer("✅ Barcha mavjud yozilish tartiblari yuborildi.")

@dp.callback_query(F.data.startswith("exm_"))
async def callback_examples(callback: types.CallbackQuery):
    kanji = callback.data.split("_")[1]
    await callback.answer("Misollar yuklanmoqda...")

    prompt = f"'{kanji}' so'zi ishtirok etgan 5 ta gapni yaponcha, o'qilishi va o'zbekcha tarjimasi bilan bering. Muhim so'zlarni **qalin** qilib belgilang."
    info = await call_gemini(prompt)

    if info:
        # Xavfli belgilarni zararsizlantirish
        clean_text = info.replace("<", "&lt;").replace(">", "&gt;")

        # Siz aytgan mantiq: barcha yulduzchalarni HTML tegiga almashtirish
        while "**" in clean_text:
            clean_text = clean_text.replace("**", "<b>", 1).replace("**", "</b>", 1)

        await callback.message.answer(
            f"📖 <b>{kanji} ishtirokida misollar:</b>\n\n{clean_text}",
            parse_mode='HTML'
        )
    else:
        await callback.message.answer(f"⚠️ <b>Kechirasiz, ma'lumot topilmadi.</b>", parse_mode='HTML')
async def main():
    logging.info("Yapon tili AI boti yangi API bilan ishga tushirildi!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot to'xtatildi.")

