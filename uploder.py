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
import math

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

# Initialize bot with proper settings
bot = Client(
    "uploader_bot", 
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=2,  # Reduced workers to prevent overload
    parse_mode=ParseMode.MARKDOWN
)

# Initialize user client for large files
user = Client(
    "user_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
    workers=2  # Reduced workers to prevent overload
)

pending_renames = {}
pending_downloads = {}

URL_REGEX = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
YOUTUBE_REGEX = r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/.+'

THUMB_LOCATION = "./THUMBNAILS"

# Override max file size to 2GB
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB in bytes

async def get_max_file_size(user_id: int) -> int:
    return MAX_FILE_SIZE

async def get_concurrent_downloads(user_id: int) -> int:
    return 5

async def save_thumb(user_id: int, thumb_path: str):
    """Save user's thumbnail"""
    os.makedirs(os.path.join(THUMB_LOCATION, str(user_id)), exist_ok=True)
    thumb_file = os.path.join(THUMB_LOCATION, str(user_id), "thumbnail.jpg")
    try:
        # Copy and convert thumbnail
        from PIL import Image
        image = Image.open(thumb_path)
        image.convert("RGB").save(thumb_file, "JPEG")
        return thumb_file
    except Exception as e:
        logging.error(f"Error saving thumbnail: {str(e)}")
        return None

def get_thumb(user_id: int):
    """Get user's saved thumbnail"""
    thumb_file = os.path.join(THUMB_LOCATION, str(user_id), "thumbnail.jpg")
    if os.path.exists(thumb_file):
        return thumb_file
    return None

def delete_thumb(user_id: int):
    """Delete user's saved thumbnail"""
    thumb_file = os.path.join(THUMB_LOCATION, str(user_id), "thumbnail.jpg")
    try:
        if os.path.exists(thumb_file):
            os.remove(thumb_file)
            return True
    except Exception as e:
        logging.error(f"Error deleting thumbnail: {str(e)}")
    return False

async def get_file_size(url):
    """Get file size from URL without downloading"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True) as response:
                if response.status == 200:
                    return int(response.headers.get('content-length', 0))
    except Exception:
        pass
    return 0

async def async_download_file(url, filename, progress=None, progress_args=None):
    """Download file using aiohttp"""
    try:
        # Check file size before downloading
        file_size = await get_file_size(url)
        if file_size > MAX_FILE_SIZE:
            raise Exception(f"File size ({humanbytes(file_size)}) is too large. Maximum allowed size is {humanbytes(MAX_FILE_SIZE)}")
        elif file_size == 0:
            # If we couldn't get the file size, we'll try downloading anyway
            logging.warning("Couldn't get file size before download")
            
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download: HTTP {response.status}")
                
                file_size = int(response.headers.get('content-length', 0))
                if file_size > MAX_FILE_SIZE:
                    raise Exception(f"File size ({humanbytes(file_size)}) is too large. Maximum allowed size is {humanbytes(MAX_FILE_SIZE)}")
                
                downloaded = 0
                start_time = time.time()
                
                with open(filename, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress:
                                try:
                                    await progress(
                                        downloaded,
                                        file_size,
                                        "📥 Downloading",
                                        progress_args[0],
                                        start_time
                                    )
                                except Exception:
                                    pass
                
                # Send completion message
                if progress and progress_args:
                    try:
                        await progress_args[0].edit("**✅ Download Complete! Starting Upload...**")
                    except Exception:
                        pass
                
                return filename
    except Exception as e:
        if os.path.exists(filename):
            os.remove(filename)
        raise e

async def send_file_with_thumbnail(client, chat_id, document, file_name, caption, progress, progress_args):
    """Send file with user's thumbnail if available"""
    thumb = get_thumb(chat_id)
    start_time = time.time()
    
    try:
        # Delete the progress message from download
        try:
            await progress_args[0].delete()
        except Exception:
            pass
        
        # Send new progress message for upload
        progress_message = await client.send_message(chat_id, "**🔄 Preparing Upload...**")
        
        try:
            # Use user client for large files
            file_size = os.path.getsize(document)
            
            # Check if user is premium
            try:
                user_me = await user.get_me()
                is_premium = user_me.is_premium
            except Exception:
                is_premium = False
            
            if file_size > 2 * 1024 * 1024 * 1024:  # If file is larger than 2GB
                if not is_premium:
                    raise Exception("User account must be premium to upload files larger than 2GB!")
                
                await progress_message.edit("**🔄 File size > 2GB, using premium user account for upload...**")
                await user.send_document(
                    chat_id=chat_id,
                    document=document,
                    thumb=thumb,
                    file_name=file_name,
                    caption=caption,
                    progress=progress,
                    progress_args=(
                        "📤 Uploading",
                        progress_message,
                        start_time
                    ),
                    force_document=True
                )
            else:
                await client.send_document(
                    chat_id=chat_id,
                    document=document,
                    thumb=thumb,
                    file_name=file_name,
                    caption=caption,
                    progress=progress,
                    progress_args=(
                        "📤 Uploading",
                        progress_message,
                        start_time
                    ),
                    force_document=True
                )
            # Delete progress message after upload
            await progress_message.delete()
        except Exception as e:
            # If sending fails, show error
            error_msg = str(e)
            if "premium" in error_msg.lower():
                error_msg = "❌ **Premium Account Required!**\n\nTo upload files larger than 2GB, the user account must be Telegram Premium."
            await progress_message.edit(f"**❌ Upload Failed!**\n\n`{error_msg}`")
            raise e
            
    except Exception as e:
        try:
            error_msg = str(e)
            if "premium" in error_msg.lower():
                error_msg = "❌ **Premium Account Required!**\n\nTo upload files larger than 2GB, the user account must be Telegram Premium."
            await progress_message.edit(f"**❌ Upload Failed!**\n\n`{error_msg}`")
        except Exception:
            pass
        raise e

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

# Create required directories
os.makedirs(DOWNLOAD_LOCATION, exist_ok=True)
os.makedirs(THUMB_LOCATION, exist_ok=True)

# Progress callback function
async def progress_for_pyrogram(current, total, ud_type, message, start):
    now = time.time()
    diff = now - start
    
    if round(diff % 10.00) == 0 or current == total:
        percentage = current * 100 / total
        speed = current / diff
        elapsed_time = round(diff) * 1000
        time_to_completion = round((total - current) / speed) * 1000
        estimated_total_time = elapsed_time + time_to_completion

        elapsed_time = TimeFormatter(milliseconds=elapsed_time)
        estimated_total_time = TimeFormatter(milliseconds=estimated_total_time)

        progress = "[{0}{1}] \nP: {2}%\n".format(
            ''.join(["█" for _ in range(math.floor(percentage / 5))]),
            ''.join(["░" for _ in range(20 - math.floor(percentage / 5))]),
            round(percentage, 2))

        tmp = progress + "{0} of {1}\nSpeed: {2}/s\nETA: {3}\n".format(
            humanbytes(current),
            humanbytes(total),
            humanbytes(speed),
            estimated_total_time if estimated_total_time != '' else "0 s"
        )
        try:
            await message.edit(
                text=f"{ud_type}\n {tmp}",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

def humanbytes(size):
    if not size:
        return ""
    power = 2**10
    n = 0
    Dic_powerN = {0: ' ', 1: 'Ki', 2: 'Mi', 3: 'Gi', 4: 'Ti'}
    while size > power:
        size /= power
        n += 1
    return str(round(size, 2)) + " " + Dic_powerN[n] + 'B'

def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "") + \
        ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2]

# Message handlers
@bot.on_message(filters.command(["start"]))
async def start_command(client, message):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ Help", callback_data="help"),
            InlineKeyboardButton("📊 About", callback_data="about")
        ],
        [
            InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
        ]
    ])
    await message.reply_text(START_TEXT, reply_markup=keyboard)

@bot.on_message(filters.command(["help"]))
async def help_command(client, message):
    await message.reply_text(HELP_TEXT)

@bot.on_message(filters.command(["about"]))
async def about_command(client, message):
    await message.reply_text(ABOUT_TEXT)

@bot.on_message(filters.command(["thumb"]))
async def handle_thumb_command(client, message):
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text("❌ Reply to a photo to set it as thumbnail.")
        return
    await save_photo(client, message)

@bot.on_message(filters.command(["delthumb"]))
async def handle_delthumb_command(client, message):
    if delete_thumb(message.chat.id):
        await message.reply_text("🗑️ Custom thumbnail deleted successfully!")
    else:
        await message.reply_text("❌ No custom thumbnail found to delete.")

@bot.on_message(filters.command(["broadcast"]) & filters.user(OWNER_ID))
async def broadcast_message(client, message):
    if not message.reply_to_message:
        await message.reply_text("❌ Please reply to a message to broadcast it.")
        return
    await broadcast_handler(client, message)

@bot.on_message(filters.private & filters.text)
async def handle_message(client, message):
    text = message.text
    chat_id = message.chat.id
    
    if not re.match(URL_REGEX, text):
        if text in pending_renames:
            # Handle rename logic...
            pass
        else:
            await message.reply_text("❌ **Please send me a valid direct download link!**")
        return
        
    url = text
    
    try:
        # Delete previous messages
        await message.delete()
    except Exception:
        pass
        
    try:
        # Send initial progress message
        progress_msg = await client.send_message(
            chat_id=chat_id,
            text="**🔄 Checking file size...**"
        )
        
        # Check file size first
        file_size = await get_file_size(url)
        if file_size > MAX_FILE_SIZE:
            await progress_msg.edit(
                f"❌ **File size ({humanbytes(file_size)}) is too large!**\n\n"
                f"Maximum allowed size is 2GB ({humanbytes(MAX_FILE_SIZE)})"
            )
            return
        elif file_size == 0:
            await progress_msg.edit("⚠️ **Couldn't determine file size, attempting download...**")
        else:
            await progress_msg.edit(f"**🔄 Starting download...**\n\nFile size: {humanbytes(file_size)}")
        
        # Start download
        filename = await get_filename(url)
        start_time = time.time()
        
        downloaded_file = await async_download_file(
            url,
            filename,
            progress=progress_for_pyrogram,
            progress_args=(progress_msg, start_time)
        )
        
        # Upload file
        await send_file_with_thumbnail(
            client,
            chat_id,
            downloaded_file,
            filename,
            f"📤 **Upload Complete!**\n\n**Filename:** `{filename}`",
            progress_for_pyrogram,
            (progress_msg, time.time())
        )
        
        # Cleanup
        try:
            os.remove(downloaded_file)
        except Exception:
            pass
            
    except Exception as e:
        error_msg = str(e)
        try:
            await progress_msg.edit(f"**❌ Download Failed!**\n\n`{error_msg}`")
        except Exception:
            await client.send_message(chat_id, f"**❌ Download Failed!**\n\n`{error_msg}`")

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    await callback_query_handler(client, callback_query)

async def start():
    """Start both bot and user client"""
    await bot.start()
    await user.start()
    print("Bot started successfully!")
    
    # Keep the bot running
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("Bot stopped!")
    finally:
        # Clean up
        asyncio.run(bot.stop())
        asyncio.run(user.stop())
