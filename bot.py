from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler

async def start(update, context):
    await update.message.reply_text("Привет!")

app = ApplicationBuilder().token("ТВОЙ_ТОКЕН").build()

app.add_handler(CommandHandler("start", start))

app.run_polling()
