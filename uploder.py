import os
import re
import uuid
import time
import logging
import asyncio
import aiohttp
from pyrogram.enums import ParseMode
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from plugins.utils import (
    async_download_file,
    get_file_size, 
    file_size_format,
    get_filename,
    progressArgs
)

from config import (
    API_ID,
    API_HASH,
    BOT_TOKEN,
    SESSION_STRING,
    MAX_FILE_SIZE,
    DOWNLOAD_LOCATION,
    OWNER_ID
)

bot = Client(
    "uploader_bot", 
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=1000,
    parse_mode=ParseMode.MARKDOWN
)

user = Client(
    "user_session",
    workers=1000,
    session_string=SESSION_STRING
)

pending_renames = {}
pending_downloads = {}

URL_REGEX = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+'

async def get_max_file_size(user_id: int) -> int:
    return MAX_FILE_SIZE

async def get_concurrent_downloads(user_id: int) -> int:
    return 5

START_TEXT = """
✨ **Welcome to URL Uploader Bot** ✨

I can help you download files from direct links and upload them to Telegram.

**Features:**
• 📥 Upload files up to 4GB
• 🎥 Support for YouTube links
• ⚡️ Fast downloads
• 📝 Custom file renaming
• 📊 Real-time progress tracking

**Commands:**
• /start - Start the bot
• /help - Get detailed help
• /about - About the bot

🔰 Send me any direct download link or YouTube link to get started!
"""

HELP_TEXT = """
📚 **URL Uploader Help**

**How to use:**
1. Send me any direct download link or YouTube link
2. Choose download options:
   • ⚡️ Quick Download - Original filename
   • ✏️ Custom Name - Rename before upload
   • ❌ Cancel - Cancel the process

**Supported Links:**
• Direct download URLs (Up to 4GB)
• YouTube video links
• Google Drive links (soon)

**Features:**
• 🚀 Fast processing
• 📊 Progress updates
• 🎯 Error reporting
• 💫 Beautiful interface

Need help? Contact @{OWNER_ID}
"""

ABOUT_TEXT = """
✨ **URL Uploader Bot**

**Version:** 2.0
**Last Updated:** 2025

🛠 **Developed with:**
• Python 3.9
• Pyrogram 2.0

📊 **Server Status:**
• Online: ✅
• Processing Speed: ⚡️
• Server Load: Optimal

Thanks for using our Bot!

©️ 2025 All Rights Reserved
"""

@bot.on_message(filters.command("start") & filters.private)
async def start_message(client, message: Message):
    chat_id = message.chat.id
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ Help", callback_data="help"),
            InlineKeyboardButton("📊 About", callback_data="about")
        ],
        [
            InlineKeyboardButton("🌟 Channel", url="https://t.me/your_channel"),
            InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
        ]
    ])
    
    await message.reply_text(
        START_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.text & filters.private)
async def handle_message(client, message: Message):
    chat_id = message.chat.id
    text = message.text.strip()

    if chat_id in pending_renames:
        new_name = text

        if not new_name:
            await message.reply_text("**Invalid filename. Please provide a valid name.**")
            return

        url = pending_renames.pop(chat_id)
        base_name, ext = os.path.splitext(url.split('/')[-1].split('?')[0])
        new_name_with_ext = f"{new_name}{ext}"

        try:
            start_time = time.time()
            editable_text = await client.send_message(chat_id, "📥 Downloading...")

            downloaded_file = await async_download_file(
                url,
                new_name_with_ext,
                progress=progress_for_pyrogram,
                progress_args=progressArgs("📥 Downloading Progress", editable_text, start_time)
            )
            
            upload_start_time = time.time()
            await message.reply_document(
                document=downloaded_file, 
                file_name=new_name_with_ext,
                caption="📤 Upload Complete!",
                progress=progress_for_pyrogram,
                progress_args=progressArgs("📤 Uploading Progress", editable_text, upload_start_time)
            )

            await editable_text.delete()
            os.remove(downloaded_file)
        except Exception as e:
            await editable_text.delete()
            await message.reply_text(f"**{str(e)}**")

    elif re.match(URL_REGEX, text) or re.match(YOUTUBE_REGEX, text):
        url = text
        try:
            file_size_bytes = await get_file_size(url)
            if file_size_bytes == 0:
                await message.reply_text("**File information is not available for this link.**")
                return

            formatted_size = file_size_format(file_size_bytes)

            filename = await get_filename(url)
            unique_id = str(uuid.uuid4())
            pending_downloads[unique_id] = {"url": url, "filename": filename}

            file_info = f"Title: `{filename}`\nSize: `{formatted_size}`"

            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚡️ Quick Download", callback_data=f"default|{unique_id}"),
                    InlineKeyboardButton("✏️ Custom Name", callback_data=f"rename|{unique_id}")
                ],
                [
                    InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{unique_id}")
                ]
            ])

            await message.reply_text(
                f"**🔗 URL Detected!**\n\n"
                f"📦 **File Size:** {formatted_size}\n"
                f"🎯 **Choose an option:**",
                reply_markup=keyboard
            )
        except Exception as e:
            await message.reply_text(
                "❌ **Error!**\n\n"
                "Unable to fetch file information.\n"
                "Please check if the URL is valid.",
                quote=True
            )

async def progress_text(current, total, start_time):
    now = time.time()
    diff = now - start_time
    
    if diff < 1:
        return ""
    
    speed = current / diff
    speed_text = file_size_format(speed) + "/s"
    
    percentage = (current * 100) / total
    
    bar_length = 10
    current_bar = int(percentage / (100 / bar_length))
    bar = "▰" * current_bar + "▱" * (bar_length - current_bar)
    
    text = (
        f"**📊 Progress Status**\n\n"
        f"**{bar}** `{percentage:.1f}%`\n\n"
        f"**⚡️ Speed:** {speed_text}\n"
        f"**📦 Size:** {file_size_format(current)} / {file_size_format(total)}\n"
    )
    
    return text

def progress_for_pyrogram(current, total):
    return progress_text(current, total, time.time())

@bot.on_message(filters.photo & filters.incoming & filters.private)
async def save_photo(client, message):
    download_location = f"{DOWNLOAD_LOCATION}/{message.from_user.id}.jpg"
    await message.download(file_name=download_location)
    await message.reply_text(text="Your custom thumbnail is saved", quote=True)

@bot.on_message(filters.command("thumb") & filters.incoming & filters.private)
async def send_photo(client, message):
    download_location = f"{DOWNLOAD_LOCATION}/{message.from_user.id}.jpg"
    if os.path.isfile(download_location):
        await message.reply_photo(
            photo=download_location, caption="Your custom thumbnail", quote=True
        )
    else:
        await message.reply_text(
            text="You don't have a set thumbnail yet! Send a .jpg image to save as thumbnail.",
            quote=True,
        )

@bot.on_message(filters.command("delthumb") & filters.incoming & filters.private)
async def delete_photo(client, message):
    download_location = f"{DOWNLOAD_LOCATION}/{message.from_user.id}.jpg"
    if os.path.isfile(download_location):
        os.remove(download_location)
        await message.reply_text(
            text="Your thumbnail removed successfully.", quote=True
        )
    else:
        await message.reply_text(
            text="You don't have a set thumbnail yet! Send a .jpg image to save as thumbnail.",
            quote=True,
        )

@bot.on_callback_query(filters.regex(r"^(default|rename|settings|about|help|cancel)\|"))
async def on_file_decision(client, callback_query):
    action, unique_id = callback_query.data.split("|")
    chat_id = callback_query.message.chat.id

    if action == "settings":
        await callback_query.message.edit_text(
            "Settings are not implemented yet.\n\n"
            "Use /thumb to set a custom thumbnail.\n"
            "Use /delthumb to delete the custom thumbnail."
        )
        return
    elif action == "about":
        await callback_query.message.edit_text(ABOUT_TEXT)
        return
    elif action == "help":
        await callback_query.message.edit_text(HELP_TEXT)
        return
    elif action == "cancel":
        await callback_query.message.edit_text(
            "**❌ Download Cancelled**\n\n"
            "Send another URL to start a new download."
        )
        return

    download_info = pending_downloads.get(unique_id)
    if not download_info:
        await callback_query.message.edit_text("**An error occurred: Invalid action.**")
        return

    url = download_info["url"]
    filename = download_info["filename"]

    try:
        file_size_bytes = await get_file_size(url)
        file_size_readable = file_size_format(file_size_bytes)

        if file_size_bytes > MAX_FILE_SIZE:
            await callback_query.message.edit_text(
                "**❌ File Too Large**\n\n"
                "Maximum file size limit: 4GB\n"
                f"Detected file size: {file_size_readable}\n\n"
                "Please try with a smaller file."
            )
            return
            
        if action == "default":
            start_time = time.time()
            editable_text = await client.send_message(chat_id, "📥 Processing your request...")

            downloaded_file = await async_download_file(
                url,
                filename,
                progress=progress_for_pyrogram,
                progress_args=progressArgs("📥 Downloading Progress", editable_text, start_time)
            )
            
            upload_start_time = time.time()
            await callback_query.message.reply_document(
                document=downloaded_file, 
                file_name=filename,
                caption="📤 Upload Complete!",
                progress=progress_for_pyrogram,
                progress_args=progressArgs("📤 Uploading Progress", editable_text, upload_start_time)
            )

            await editable_text.delete()
            await callback_query.message.delete()
            os.remove(downloaded_file)

        elif action == "rename":
            pending_renames[chat_id] = url
            await callback_query.message.edit_text("✏️ Send the new name for the file")

    except Exception as e:
        await editable_text.delete()
        await callback_query.message.edit_text(f"{str(e)}")

@bot.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_message(client, message: Message):
    if not message.reply_to_message:
        await message.reply_text("Please reply to a message to broadcast.")
        return

    broadcast_text = message.reply_to_message.text
    if not broadcast_text:
        await message.reply_text("The replied message does not contain any text.")
        return

    try:
        await client.send_message(chat_id=OWNER_ID, text=broadcast_text)
        await message.reply_text("✅ Broadcast message sent successfully!")
    except Exception as e:
        await message.reply_text(f"❌ Failed to send broadcast: {str(e)}")

if __name__ == "__main__":
    user.start()
    bot.run()
