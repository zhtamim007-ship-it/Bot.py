import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

# Credentials
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
GITHUB_TOKEN = "YOUR_GITHUB_PAT_TOKEN"
REPO_OWNER = "YOUR_GITHUB_USERNAME"
REPO_NAME = "YOUR_REPO_NAME"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("Create RDP 6 Hour 🚀", callback_data="create_rdp")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Welcome to Windows RDP Bot!", reply_markup=reply_markup)

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "create_rdp":
        await query.edit_message_text("⌛ Setting up Cloud Node session... Please wait 1-2 mins.")
        
        # Trigger GitHub Actions API
        url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/actions/workflows/rdp.yml/dispatches"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json"
        }
        payload = {
            "ref": "main",
            "inputs": {"chat_id": str(query.message.chat_id)}
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 204:
            await query.message.reply_text("🔄 Deployment triggered on GitHub! You will receive credentials once ready.")
        else:
            await query.message.reply_text("❌ Failed to initiate RDP workflow. Check GitHub Token/Repo settings.")

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_click))
    print("Bot is running...")
    app.run_polling()
  
