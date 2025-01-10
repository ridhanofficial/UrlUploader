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
import yt_dlp

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

# Fallback for THUMB_LOCATION if not imported
THUMB_LOCATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thumb")

# Ensure thumbnail directory exists
os.makedirs(THUMB_LOCATION, exist_ok=True)

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

# Constants and storage
pending_downloads = {}
pending_renames = {}
URL_REGEX = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
YOUTUBE_REGEX = r'(?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]+)'

async def extract_youtube_info(url):
    """Extract info from YouTube URL"""
    ydl_opts = {
        'format': 'best',  # Best quality
        'noplaylist': True,  # Only download single video
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            # Get best quality that's under size limit
            for f in formats:
                if f.get('filesize', 0) < MAX_FILE_SIZE:
                    return {
                        'url': f['url'],
                        'title': info.get('title', 'video'),
                        'thumbnail': info.get('thumbnail'),
                        'duration': info.get('duration'),
                        'filesize': f.get('filesize', 0)
                    }
            
            return None
    except Exception as e:
        print(f"YouTube extraction error: {str(e)}")
        return None

async def process_youtube(client, message, url):
    """Process YouTube URL"""
    try:
        progress_msg = await message.reply_text("🎥 **Processing YouTube Link...**")
        
        # Extract info
        info = await extract_youtube_info(url)
        if not info:
            await progress_msg.edit_text("❌ **Failed to process YouTube video**\n\nMake sure the video exists and is not too large.")
            return
            
        # Check file size
        if info['filesize'] > MAX_FILE_SIZE:
            await progress_msg.edit_text(
                f"❌ **Video size ({humanbytes(info['filesize'])}) is too large!**\n\n"
                f"Maximum allowed size is 2GB ({humanbytes(MAX_FILE_SIZE)})"
            )
            return
            
        # Show download options
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡️ Quick Download", callback_data=f"ytdl|{url}|default"),
                InlineKeyboardButton("✏️ Custom Name", callback_data=f"ytdl|{url}|rename")
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ]
        ])
        
        await progress_msg.edit_text(
            f"🎥 **YouTube Video Found!**\n\n"
            f"📝 **Title:** {info['title']}\n"
            f"⏱ **Duration:** {TimeFormatter(info['duration'] * 1000) if info['duration'] else 'N/A'}\n"
            f"📦 **Size:** {humanbytes(info['filesize'])}\n\n"
            "**Choose an option:**",
            reply_markup=keyboard
        )
        
    except Exception as e:
        await message.reply_text(f"❌ **Error processing YouTube link:**\n\n`{str(e)}`")

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

# Create required directories
os.makedirs(DOWNLOAD_LOCATION, exist_ok=True)

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

async def check_user_premium(user_id: int) -> bool:
    """Check if user has premium features"""
    try:
        # Implement your premium check logic here
        # This is a placeholder - replace with actual premium verification
        return False
    except Exception:
        return False

# Bot start text with dynamic premium info
START_TEXT = """
👋 **Welcome to URL Uploader Bot!**

Your Status: {premium_status}
Storage: {storage_limit}

I can help you upload files from various sources:
• Direct URLs 
• YouTube links
• Telegram files

**Features Available:**
{features}

Use /help to see all available commands.
"""

async def get_user_info(user_id: int):
    """Get user's premium status and features"""
    is_premium = await check_user_premium(user_id)
    
    if is_premium:
        status = "🌟 Premium User"
        storage = "Up to 4GB per file"
        features = """
• Upload files up to 4GB
• Priority processing
• Custom thumbnails
• Advanced file naming
• Premium support"""
    else:
        status = "⭐ Free User"
        storage = "Up to 2GB per file"
        features = """
• Upload files up to 2GB
• Basic thumbnails
• Standard support"""
        
    return status, storage, features

@bot.on_message(filters.command(["start"]))
async def start_command(client, message):
    """Handle the /start command with premium info"""
    # Get user's premium status
    status, storage, features = await get_user_info(message.from_user.id)
    
    # Create premium-aware keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("⭐ Premium", callback_data="premium_info")
        ],
        [
            InlineKeyboardButton("❓ Help", callback_data="help"),
            InlineKeyboardButton("🤖 About", callback_data="about")
        ]
    ])

    # Send start message with premium info
    await message.reply_text(
        START_TEXT.format(
            premium_status=status,
            storage_limit=storage,
            features=features
        ),
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    """Handle inline button callbacks"""
    data = callback_query.data
    
    # Premium info handler
    if data == "premium_info":
        is_premium = await check_user_premium(callback_query.from_user.id)
        
        if is_premium:
            text = """
🌟 **Premium User Features**

• 4GB file uploads
• Priority processing
• Custom thumbnails
• Advanced file naming
• Premium support

You are already enjoying premium features! 🎉
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start")]
            ])
        else:
            text = """
⭐ **Upgrade to Premium**

Unlock exclusive features:
• Upload files up to 4GB
• Priority processing
• Custom thumbnails
• Advanced file naming
• Premium support

Current Status: Free User
"""
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Upgrade Now", url="https://t.me/your_premium_bot")],
                [InlineKeyboardButton("🔙 Back", callback_data="start")]
            ])
            
        await callback_query.edit_message_text(
            text,
            reply_markup=keyboard
        )
    
    # Help callback
    elif data == "help":
        help_text = """
📘 **Bot Help & Commands**

• `/start` - Start the bot
• `/help` - Show help message
• `/about` - About the bot
• `/thumb` - Set custom thumbnail
• `/delthumb` - Delete thumbnail
• `/showthumb` - View thumbnail

**Uploading Files:**
1. Send direct URL
2. Send YouTube link
3. Upload file directly
"""
        await callback_query.edit_message_text(
            help_text, 
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start")]
            ])
        )
    
    # About callback
    elif data == "about":
        about_text = """
🤖 **URL Uploader Bot**

**Features:**
• Upload files from URLs
• YouTube video downloads
• Custom thumbnails
• File size up to 2GB

**Created with ❤️ by Your Team**
"""
        await callback_query.edit_message_text(
            about_text,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back", callback_data="start")]
            ])
        )
    
    # Settings callback
    elif data == "settings":
        await OpenSettings(callback_query.message)
    
    # Return to start
    elif data == "start":
        status, storage, features = await get_user_info(callback_query.from_user.id)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("⭐ Premium", callback_data="premium_info")
            ],
            [
                InlineKeyboardButton("❓ Help", callback_data="help"),
                InlineKeyboardButton("🤖 About", callback_data="about")
            ]
        ])
        await callback_query.edit_message_text(
            START_TEXT.format(
                premium_status=status,
                storage_limit=storage,
                features=features
            ), 
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    
    # Close callback
    elif data == "close":
        await callback_query.message.delete()
    
    # Acknowledge the callback query
    await callback_query.answer()

async def save_photo(client, message):
    """Save photo as thumbnail"""
    try:
        # Ensure the reply is to a photo
        if not message.reply_to_message or not message.reply_to_message.photo:
            await message.reply_text("❌ Reply to a photo to set it as thumbnail.")
            return

        # Get the photo file
        photo = message.reply_to_message.photo[-1]
        download_path = os.path.join(THUMB_LOCATION, f"{message.chat.id}_temp.jpg")
        
        # Download the photo
        await client.download_media(
            message=photo,
            file_name=download_path
        )
        
        # Save as thumbnail
        thumb_path = await save_thumb(message.chat.id, download_path)
        
        if thumb_path:
            await message.reply_text("✅ **Custom thumbnail saved successfully!**")
        else:
            await message.reply_text("❌ **Failed to save thumbnail!**")
            
        # Cleanup temp file
        try:
            os.remove(download_path)
        except:
            pass
            
    except Exception as e:
        await message.reply_text(f"❌ **Error saving thumbnail:**\n\n`{str(e)}`")

@bot.on_message(filters.command(["thumb"]))
async def handle_thumb_command(client, message):
    """Handle thumbnail command"""
    if message.reply_to_message and message.reply_to_message.photo:
        # Save thumbnail
        await save_photo(client, message)
    else:
        # Show current thumbnail
        thumb = get_thumb(message.chat.id)
        if thumb:
            await message.reply_photo(
                photo=thumb,
                caption="🖼️ **Your current thumbnail**\n\n"
                "• Reply to a photo with /thumb to change it\n"
                "• Use /delthumb to remove it"
            )
        else:
            await message.reply_text(
                "❌ **No thumbnail set!**\n\n"
                "• Reply to a photo with /thumb to set it"
            )

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
    
    if text.startswith("/"):
        return  # Let command handlers handle commands
        
    # Check if this is a rename request
    if chat_id in pending_renames:
        if text.lower() == "/cancel":
            pending_renames.pop(chat_id)
            await message.reply_text("❌ Process Cancelled")
            return
            
        rename_info = pending_renames.pop(chat_id)
        if rename_info.get("type") == "youtube":
            # Handle YouTube rename
            await download_youtube(client, message, rename_info["url"], text)
        else:
            # Handle normal file rename
            await handle_download(client, message, rename_info["url"], text)
        return
        
    # Check if URL is YouTube
    if re.match(YOUTUBE_REGEX, text):
        await process_youtube(client, message, text)
    elif re.match(URL_REGEX, text):
        # Handle normal URL download
        file_id = str(uuid.uuid4())
        pending_downloads[file_id] = text
        
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚡️ Quick Download", callback_data=f"default|{file_id}"),
                InlineKeyboardButton("✏️ Custom Name", callback_data=f"rename|{file_id}")
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel|{file_id}")
            ]
        ])
        
        await message.reply_text(
            "🔗 **URL Detected!**\n\n"
            "Choose an option:",
            reply_markup=keyboard
        )
    else:
        await message.reply_text("❌ **Please send me a valid direct download link or YouTube URL!**")

async def start():
    """Start both bot and user client"""
    try:
        await bot.start()
        await user.start()
        print("Bot started successfully!")
        
        # Keep the bot running
        while True:
            await asyncio.sleep(60)  # Sleep for 60 seconds
            
    except Exception as e:
        print(f"Error: {str(e)}")
    finally:
        # Cleanup
        await bot.stop()
        await user.stop()

def main():
    """Run the bot"""
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start())
    except KeyboardInterrupt:
        print("Bot stopped!")
    finally:
        loop.close()

if __name__ == "__main__":
    main()
4
