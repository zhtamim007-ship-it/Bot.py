import os
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Render Environment Variables থেকে ডাটা রিড করা
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_OWNER = os.environ.get("REPO_OWNER")
REPO_NAME = os.environ.get("REPO_NAME")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Create RDP 6 Hour 🚀", callback_data="create_rdp")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to Windows RDP Bot!", reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "create_rdp":
        await query.edit_message_text("⌛ Setting up Cloud Node session... Please wait 1-2 mins.")
        
        # GitHub Actions API Trigger
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/rdp.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        payload = {
            "ref": "main",
            "inputs": {"chat_id": str(query.message.chat_id)}
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload)
            if response.status_code == 204:
                await query.message.reply_text("🔄 Deployment triggered on GitHub! You will receive credentials once ready.")
            else:
                await query.message.reply_text(f"❌ Failed to initiate RDP. Status Code: {response.status_code}")
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {str(e)}")

if __name__ == '__main__':
    if not BOT_TOKEN:
        print("CRITICAL ERROR: BOT_TOKEN is missing! Add BOT_TOKEN in Render Environment Variables.")
        exit(1)
        
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    print("Bot is running...")
    app.run_polling()
    
