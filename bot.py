"""
Телеграм-бот для финансового трекера
Команды:
  /start — приветствие
  /help  — справка
  /stats — статистика за месяц
  /list  — последние 5 операций
  /clear — очистить все операции

Форматы сообщений:
  кофе 350             → расход, категория "Другое"
  продукты 1200 Еда    → расход, категория "Еда"
  зарплата +85000      → доход
  такси 450 Транспорт  → расход, категория "Транспорт"
"""

import os, re, json
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from supabase import create_client, Client

# ── Настройки (берутся из переменных окружения) ──
BOT_TOKEN     = os.environ["BOT_TOKEN"]
SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

CATEGORIES = ["Еда", "Транспорт", "Жильё", "Развлечения", "Здоровье", "Одежда", "Другое"]

def parse_message(text: str):
    """Парсит сообщение вида 'кофе 350 Еда' или 'зарплата +85000'"""
    text = text.strip()
    # Ищем число (с + для дохода)
    match = re.search(r'([+-]?\d+(?:[.,]\d+)?)', text)
    if not match:
        return None
    amount_str = match.group(1).replace(',', '.')
    amount = float(amount_str)
    tx_type = "income" if amount > 0 or text.startswith('+') else "expense"
    amount = abs(amount)

    # Убираем число из текста
    rest = (text[:match.start()] + text[match.end():]).strip()

    # Ищем категорию
    category = "Другое"
    note_parts = []
    for word in rest.split():
        if word.capitalize() in CATEGORIES:
            category = word.capitalize()
        else:
            note_parts.append(word)

    note = " ".join(note_parts).strip() or category
    return {"type": tx_type, "amount": amount, "category": category, "note": note}

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я твой финансовый помощник.\n\n"
        "Просто напиши мне трату, например:\n"
        "  • кофе 350\n"
        "  • продукты 1200 Еда\n"
        "  • такси 450 Транспорт\n"
        "  • зарплата +85000\n\n"
        "Все данные сразу появятся в твоём трекере 📊\n\n"
        "/help — все команды"
    )

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Справка:\n\n"
        "Форматы записи:\n"
        "  название сумма [категория]\n"
        "  + перед суммой = доход\n\n"
        "Категории: " + ", ".join(CATEGORIES) + "\n\n"
        "Команды:\n"
        "  /stats — статистика за месяц\n"
        "  /list  — последние операции\n"
        "  /clear — очистить все данные"
    )

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text

    parsed = parse_message(text)
    if not parsed:
        await update.message.reply_text("❓ Не понял. Напиши, например: кофе 350 или продукты 1200 Еда")
        return

    # Сохраняем в Supabase
    record = {
        "user_id": user_id,
        "type": parsed["type"],
        "amount": parsed["amount"],
        "category": parsed["category"],
        "note": parsed["note"],
        "date": datetime.now().strftime("%Y-%m-%d"),
        "card": "Телеграм",
    }
    supabase.table("transactions").insert(record).execute()

    emoji = "💚" if parsed["type"] == "income" else "🔴"
    sign  = "+" if parsed["type"] == "income" else "−"
    await update.message.reply_text(
        f"{emoji} Записано!\n"
        f"  {parsed['note']} — {sign}{parsed['amount']:,.0f} ₽\n"
        f"  Категория: {parsed['category']}\n"
        f"  Дата: {record['date']}"
    )

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    month = datetime.now().strftime("%Y-%m")

    res = supabase.table("transactions")\
        .select("*")\
        .eq("user_id", user_id)\
        .gte("date", f"{month}-01")\
        .execute()

    rows = res.data or []
    expenses = sum(r["amount"] for r in rows if r["type"] == "expense")
    incomes  = sum(r["amount"] for r in rows if r["type"] == "income")

    # По категориям
    by_cat = {}
    for r in rows:
        if r["type"] == "expense":
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + r["amount"]

    cat_lines = "\n".join(f"  {cat}: {amt:,.0f} ₽" for cat, amt in sorted(by_cat.items(), key=lambda x: -x[1]))

    await update.message.reply_text(
        f"📊 Статистика за {month}:\n\n"
        f"💚 Доходы:  {incomes:,.0f} ₽\n"
        f"🔴 Расходы: {expenses:,.0f} ₽\n"
        f"💰 Баланс:  {incomes-expenses:,.0f} ₽\n\n"
        f"По категориям:\n{cat_lines or '  Нет данных'}"
    )

async def list_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    res = supabase.table("transactions")\
        .select("*")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(5)\
        .execute()

    rows = res.data or []
    if not rows:
        await update.message.reply_text("Нет операций.")
        return

    lines = []
    for r in rows:
        sign = "+" if r["type"] == "income" else "−"
        lines.append(f"  {r['date']} {r['note']} {sign}{r['amount']:,.0f} ₽ [{r['category']}]")

    await update.message.reply_text("📋 Последние операции:\n\n" + "\n".join(lines))

async def clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("✅ Да, очистить", callback_data="confirm_clear"),
        InlineKeyboardButton("❌ Отмена", callback_data="cancel_clear"),
    ]]
    await update.message.reply_text("Удалить все операции?", reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(query.from_user.id)
    await query.answer()
    if query.data == "confirm_clear":
        supabase.table("transactions").delete().eq("user_id", user_id).execute()
        await query.edit_message_text("✅ Все операции удалены.")
    else:
        await query.edit_message_text("Отменено.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("list",  list_cmd))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Бот запущен...")
    app.run_polling()
