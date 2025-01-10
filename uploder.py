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

THUMB_LOCATION = "./THUMBNAILS"

# Constants
FORCE_SUB_CHANNEL = "@RSforeverBots"
MAX_FILE_SIZE = 2000 * 1024 * 1024  # 2000 MiB in bytes

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

async def force_sub(client, message: Message):
    """Check if user has joined the channel"""
    try:
        user_id = message.from_user.id
        if FORCE_SUB_CHANNEL.startswith("@"):
            channel = FORCE_SUB_CHANNEL
        else:
            channel = "@" + FORCE_SUB_CHANNEL
            
        try:
            await client.get_chat_member(channel, user_id)
            return True
        except UserNotParticipant:
            buttons = [[
                InlineKeyboardButton("🔔 Join Channel", url=f"https://t.me/{channel.replace('@', '')}")
            ]]
            await message.reply_text(
                f"**❗️ You must join our channel to use this bot!**\n\n"
                f"Please join @{channel.replace('@', '')} and try again.",
                reply_markup=InlineKeyboardMarkup(buttons),
                quote=True
            )
            return False
    except Exception as e:
        logging.error(f"Force sub error: {str(e)}")
        return True

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

# Update the download handlers to handle completion properly
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
                )
            )
            # Delete progress message after upload
            await progress_message.delete()
        except Exception as e:
            # If sending with thumbnail fails, try without it
            await client.send_document(
                chat_id=chat_id,
                document=document,
                file_name=file_name,
                caption=caption,
                progress=progress,
                progress_args=(
                    "📤 Uploading",
                    progress_message,
                    start_time
                )
            )
            # Delete progress message after upload
            await progress_message.delete()
            
    except Exception as e:
        try:
            await progress_message.edit(f"**❌ Upload Failed!**\n\n`{str(e)}`")
        except Exception:
            pass
        raise e

# Update the message handlers
@bot.on_message(filters.text & filters.private & ~filters.command("start") & ~filters.command("help") & ~filters.command("about"))
async def handle_message(client, message: Message):
    if not await force_sub(client, message):
        return
        
    text = message.text.strip()
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
                f"Maximum allowed size is {humanbytes(MAX_FILE_SIZE)}"
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
        error_msg = f"**❌ Download Failed!**\n\n`{str(e)}`"
        try:
            await progress_msg.edit(error_msg)
        except Exception:
            await client.send_message(chat_id, error_msg)

# Command handlers
@bot.on_message(filters.command(["start"]) & filters.private)
async def start_command(client, message: Message):
    if not await force_sub(client, message):
        return
    
    chat_id = message.chat.id
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✨ Help", callback_data="help"),
            InlineKeyboardButton("📊 About", callback_data="about")
        ],
        [
            InlineKeyboardButton("🌟 Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}"),
            InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
        ]
    ])
    
    await message.reply_text(
        START_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.command(["help"]) & filters.private)
async def help_command(client, message: Message):
    if not await force_sub(client, message):
        return
        
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="start"),
            InlineKeyboardButton("📊 About", callback_data="about")
        ]
    ])
    
    await message.reply_text(
        HELP_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.command(["about"]) & filters.private)
async def about_command(client, message: Message):
    if not await force_sub(client, message):
        return
        
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="start"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ]
    ])
    
    await message.reply_text(
        ABOUT_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

# Callback query handler for inline buttons
@bot.on_callback_query()
async def callback_handler(client, callback_query):
    data = callback_query.data
    chat_id = callback_query.message.chat.id
    
    if data == "start":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✨ Help", callback_data="help"),
                InlineKeyboardButton("📊 About", callback_data="about")
            ],
            [
                InlineKeyboardButton("🌟 Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL.replace('@', '')}"),
                InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
            ]
        ])
        
        await callback_query.message.edit_text(
            START_TEXT,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    elif data == "help":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Back to Start", callback_data="start"),
                InlineKeyboardButton("📊 About", callback_data="about")
            ]
        ])
        
        await callback_query.message.edit_text(
            HELP_TEXT,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    elif data == "about":
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Back to Start", callback_data="start"),
                InlineKeyboardButton("❓ Help", callback_data="help")
            ]
        ])
        
        await callback_query.message.edit_text(
            ABOUT_TEXT,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    elif "|" in data:
        # Handle file download/rename callbacks
        action, unique_id = data.split("|")
        
        if action == "cancel":
            if unique_id in pending_downloads:
                pending_downloads.pop(unique_id)
            await callback_query.message.edit_text(
                "**❌ Download Cancelled**\n\n"
                "Send another URL to start a new download."
            )
            return
        
        # Get URL from stored data
        download_info = pending_downloads.get(unique_id)
        if not download_info:
            await callback_query.message.edit_text(
                "**❌ Error: Download information not found**\n\n"
                "Please send the URL again."
            )
            return
        
        url = download_info["url"]
        
        try:
            processing_msg = await callback_query.message.edit_text(
                "**🔄 Processing Request**\n\n"
                "⚡️ Initializing download...\n"
                "📊 Preparing file information..."
            )
            
            file_size_bytes = await get_file_size(url)
            file_size_readable = file_size_format(file_size_bytes)
            
            if file_size_bytes > MAX_FILE_SIZE:
                await processing_msg.edit_text(
                    "**❌ File Too Large**\n\n"
                    "Maximum file size limit: 4GB\n"
                    f"Detected file size: {file_size_readable}\n\n"
                    "Please try with a smaller file."
                )
                pending_downloads.pop(unique_id)
                return
            
            if action == "default":
                # Download with original filename
                filename = await get_filename(url)
                start_time = time.time()
                editable_text = await client.send_message(
                    chat_id=chat_id,
                    text="📥 Starting Download..."
                )
                
                downloaded_file = await async_download_file(
                    url,
                    filename,
                    progress=progress_for_pyrogram,
                    progress_args=(editable_text, start_time)
                )
                
                upload_start_time = time.time()
                await send_file_with_thumbnail(
                    client,
                    chat_id,
                    downloaded_file,
                    filename,
                    f"📤 **Upload Complete!**\n\n**Filename:** `{filename}`",
                    progress_for_pyrogram,
                    (editable_text, upload_start_time)
                )
                
                await editable_text.delete()
                await processing_msg.delete()
                os.remove(downloaded_file)
                pending_downloads.pop(unique_id)
            
            elif action == "rename":
                # Store URL for rename
                pending_renames[chat_id] = url
                pending_downloads.pop(unique_id)
                
                # Get original filename
                original_filename = await get_filename(url)
                
                await processing_msg.edit_text(
                    "**✏️ Send me the new filename**\n\n"
                    f"**Original filename:** `{original_filename}`\n\n"
                    "• Send the new name without extension\n"
                    "• Extension will be added automatically\n"
                    "• Send /cancel to cancel the process"
                )
        
        except Exception as e:
            if unique_id in pending_downloads:
                pending_downloads.pop(unique_id)
            await processing_msg.edit_text(
                f"**❌ Error occurred:**\n\n`{str(e)}`"
            )
    
    # Answer the callback query
    await callback_query.answer()

# Handle text messages (URLs and rename requests)
@bot.on_message(filters.text & filters.private & ~filters.command("start") & ~filters.command("help") & ~filters.command("about"))
async def handle_message(client, message: Message):
    if not await force_sub(client, message):
        return
        
    text = message.text.strip()
    chat_id = message.chat.id
    
    # Check if this is a rename request
    if chat_id in pending_renames:
        if text.lower() == "/cancel":
            pending_renames.pop(chat_id)
            await message.reply_text("❌ Process Cancelled")
            return
        
        # Process rename request
        try:
            url = pending_renames[chat_id]
            new_name = text
            
            # Get original file extension
            original_filename = await get_filename(url)
            _, ext = os.path.splitext(original_filename)
            
            # Add extension if not provided
            if not ext:
                ext = ".mp4"  # Default extension
            if not new_name.endswith(ext):
                new_name_with_ext = f"{new_name}{ext}"
            else:
                new_name_with_ext = new_name
            
            # Start download process
            start_time = time.time()
            status_msg = await message.reply_text(
                "**🔄 Processing Download**\n\n"
                f"**New filename:** `{new_name_with_ext}`\n"
                "**Status:** Downloading..."
            )
            
            downloaded_file = await async_download_file(
                url,
                new_name_with_ext,
                progress=progress_for_pyrogram,
                progress_args=(status_msg, start_time)
            )
            
            # Start upload process
            await send_file_with_thumbnail(
                client,
                chat_id,
                downloaded_file,
                new_name_with_ext,
                f"📤 **Upload Complete!**\n\n**Filename:** `{new_name_with_ext}`",
                progress_for_pyrogram,
                (status_msg, time.time())
            )
            
            # Cleanup
            await status_msg.delete()
            os.remove(downloaded_file)
            pending_renames.pop(chat_id)
            
        except Exception as e:
            error_msg = f"**❌ Error occurred:**\n\n`{str(e)}`"
            await message.reply_text(error_msg)
            if chat_id in pending_renames:
                pending_renames.pop(chat_id)
        return
    
    # Handle URL
    if re.match(URL_REGEX, text):
        unique_id = str(uuid.uuid4())
        # Store URL for later use
        pending_downloads[unique_id] = {
            "url": text,
            "message_id": message.id,
            "chat_id": chat_id
        }
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡️ Quick Download", callback_data=f"default|{unique_id}"),
                InlineKeyboardButton("✏️ Custom Name", callback_data=f"rename|{unique_id}")
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{unique_id}")
            ]
        ])
        
        try:
            file_size = await get_file_size(text)
            size_text = file_size_format(file_size)
            original_filename = await get_filename(text)
            
            await message.reply_text(
                f"**🔗 URL Detected!**\n\n"
                f"📦 **File Size:** {size_text}\n"
                f"📄 **Original Name:** `{original_filename}`\n"
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
            if unique_id in pending_downloads:
                pending_downloads.pop(unique_id)

@bot.on_message(filters.photo & filters.incoming & filters.private)
async def save_photo(client, message):
    download_location = f"{DOWNLOAD_LOCATION}/{message.from_user.id}.jpg"
    await message.download(file_name=download_location)
    await message.reply_text(text="Your custom thumbnail is saved", quote=True)

@bot.on_message(filters.command("thumb") & filters.incoming & filters.private)
async def handle_thumb_command(client, message: Message):
    if not await force_sub(client, message):
        return
        
    user_id = message.from_user.id
    
    if message.reply_to_message and message.reply_to_message.photo:
        # User replied to a photo with the command
        try:
            progress_msg = await message.reply_text("**🔄 Processing thumbnail...**")
            
            # Download the photo
            thumb_path = await message.reply_to_message.download()
            
            # Save the thumbnail
            saved_thumb = await save_thumb(user_id, thumb_path)
            
            # Clean up downloaded file
            os.remove(thumb_path)
            
            if saved_thumb:
                await progress_msg.edit_text(
                    "**✅ Custom thumbnail saved successfully!**\n\n"
                    "This thumbnail will be used for all your uploads.\n"
                    "• Use /delthumb to remove it\n"
                    "• Send /thumb again with another photo to change it"
                )
            else:
                await progress_msg.edit_text("**❌ Failed to save thumbnail**")
        except Exception as e:
            await message.reply_text(f"**❌ Error:** `{str(e)}`")
    else:
        # Check if user has a thumbnail
        thumb_file = get_thumb(user_id)
        if thumb_file:
            try:
                await message.reply_photo(
                    photo=thumb_file,
                    caption="**🖼️ Your current thumbnail**\n\n"
                            "• Reply to a photo with /thumb to change it\n"
                            "• Use /delthumb to remove it"
                )
            except Exception as e:
                await message.reply_text("**❌ Error showing thumbnail**")
        else:
            await message.reply_text(
                "**🖼️ No thumbnail set**\n\n"
                "• Reply to a photo with /thumb to set it\n"
                "• The thumbnail will be used for all your uploads"
            )

@bot.on_message(filters.command("delthumb") & filters.incoming & filters.private)
async def handle_delthumb_command(client, message: Message):
    if not await force_sub(client, message):
        return
        
    user_id = message.from_user.id
    
    if delete_thumb(user_id):
        await message.reply_text("**✅ Custom thumbnail deleted successfully!**")
    else:
        await message.reply_text("**❌ No thumbnail found to delete**")

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

async def start_bot():
    """Start the bot with flood wait handling"""
    while True:
        try:
            await bot.start()
            print("Bot started successfully!")
            break
        except Exception as e:
            if isinstance(e, pyrogram.errors.FloodWait):
                print(f"Flood wait error, sleeping for {e.value} seconds")
                await asyncio.sleep(e.value)
            else:
                print(f"Failed to start bot: {str(e)}")
                raise e

if __name__ == "__main__":
    user.start()
    asyncio.get_event_loop().run_until_complete(start_bot())
    bot.idle()
