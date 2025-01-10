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
from pyrogram.errors import FloodWait
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

# Define FORCE_SUB_CHANNEL if not present in config
try:
    from config import FORCE_SUB_CHANNEL
except ImportError:
    FORCE_SUB_CHANNEL = "@RSforeverBots"  # Default channel

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
    ydl_opts = {
        'format': 'best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats = info.get('formats', [])
            
            # Get best quality format
            for f in formats:
                return {
                    'url': f['url'],
                    'title': info.get('title', 'video'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration'),
                    'filesize': f.get('filesize', 0)
                }
            
            return None
    except Exception as e:
        logging.error(f"YouTube extraction error: {str(e)}")
        return None

async def process_youtube(client, message, url):
    try:
        progress_msg = await message.reply_text("🎥 **Processing YouTube Link...**")
        
        # Extract info
        info = await extract_youtube_info(url)
        if not info:
            await progress_msg.edit_text("❌ **Failed to process YouTube video**\n\nMake sure the video exists.")
            return
        
        # Check file size (2GB limit)
        if info['filesize'] > 2 * 1024 * 1024 * 1024:  # 2GB in bytes
            await progress_msg.edit_text(
                f"❌ **Video size ({humanbytes(info['filesize'])}) is too large!**\n\n"
                "Maximum allowed size is 2GB"
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
        
        # Send message with video details
        await progress_msg.edit_text(
            f"**🎥 YouTube Video Detected!**\n\n"
            f"📹 **Title:** `{info['title']}`\n"
            f"⏱️ **Duration:** {info['duration']} seconds\n"
            f"📦 **Size:** {humanbytes(info['filesize'])}\n"
            f"🎯 **Choose an option:**",
            reply_markup=keyboard
        )
    
    except Exception as e:
        logging.error(f"YouTube processing error: {str(e)}")
        await message.reply_text("❌ **Failed to process YouTube video**")

async def get_max_file_size(user_id: int) -> int:
    return MAX_FILE_SIZE

async def get_concurrent_downloads(user_id: int) -> int:
    return 5

async def save_thumb(user_id: int, thumb_path: str):
    try:
        os.makedirs(THUMB_LOCATION, exist_ok=True)
        
        user_thumb_file = os.path.join(THUMB_LOCATION, f"{user_id}_thumb.txt")
        
        with open(user_thumb_file, 'w') as f:
            f.write(thumb_path)
        
        return True
    except Exception as e:
        logging.error(f"Error saving thumb for user {user_id}: {str(e)}")
        return False

def get_thumb(user_id: int):
    try:
        user_thumb_file = os.path.join(THUMB_LOCATION, f"{user_id}_thumb.txt")
        
        if os.path.exists(user_thumb_file):
            with open(user_thumb_file, 'r') as f:
                thumb_path = f.read().strip()
            
            if os.path.exists(thumb_path):
                return thumb_path
        
        return None
    except Exception as e:
        logging.error(f"Error retrieving thumb for user {user_id}: {str(e)}")
        return None

async def save_photo(client, message):
    os.makedirs(THUMB_LOCATION, exist_ok=True)
    
    try:
        if not message.reply_to_message or not message.reply_to_message.photo:
            await message.reply_text("❌ Please reply to a photo to set it as thumbnail.")
            return
        
        photo = message.reply_to_message.photo
        largest_photo = photo[-1]
        
        thumb_path = os.path.join(
            THUMB_LOCATION, 
            f"{message.from_user.id}_thumb.jpg"
        )
        
        await client.download_media(
            message.reply_to_message, 
            file_name=thumb_path
        )
        
        await save_thumb(message.from_user.id, thumb_path)
        
        await message.reply_text(
            "✅ **Thumbnail saved successfully!**\n"
            "This thumbnail will be used for your future uploads."
        )
    
    except Exception as e:
        logging.error(f"Error saving thumbnail: {str(e)}")
        await message.reply_text(f"❌ Error saving thumbnail: {str(e)}")

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
            await progress_message.edit(f"**❌ Upload Failed!**\n\n`{error_msg}`")
            raise e
            
    except Exception as e:
        try:
            error_msg = str(e)
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
    """Always return False for free option only"""
    return False

async def get_user_info(user_id: int):
    """Get user's features for free tier"""
    return "⭐ Free User", "Up to 2GB per file", """
• Upload files up to 2GB
• Basic thumbnails
• Standard support"""

# Bot about text
ABOUT_TEXT = """
🤖 **URL Uploader Bot**

**Version:** 2.0 Free Edition
**Developer:** Your Name

**Features:**
• Upload files up to 2GB
• Direct URL downloads
• YouTube link support
• Custom thumbnails
• File renaming

**Support:**
• Telegram: @your_support_username
• GitHub: [Your GitHub Repo]

Thank you for using our bot! 
"""

START_TEXT = """
👋 **Welcome to URL Uploader Bot!**

Your Status: {status}
Storage: {storage}

I can help you upload files from various sources:
• Direct URLs 
• YouTube links
• Telegram files

**Features Available:**
{features}

Use /help to see all available commands.
"""

HELP_TEXT = """
**Available Commands:**

• `/start` - Start the bot
• `/help` - Show this help message
• `/about` - About the bot
• `/thumb` - Set a custom thumbnail
• `/delthumb` - Delete custom thumbnail
• `/broadcast` - Broadcast a message (Owner only)

**Usage:**

• Send a direct download link or YouTube URL to upload a file
• Use `/thumb` to set a custom thumbnail
• Use `/delthumb` to delete the custom thumbnail
"""

@bot.on_message(filters.command(["help"]) & filters.private)
async def help_command(client, message: Message):
    # Store the original message ID
    original_message_id = message.id

    # Delete only the user's command message
    try:
        await client.delete_messages(
            chat_id=message.chat.id, 
            message_ids=[original_message_id]
        )
    except Exception:
        pass

    # Create keyboard for help
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="start")
        ]
    ])
    
    # Send help message
    await client.send_message(
        chat_id=message.chat.id,
        text=HELP_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.command(["about"]) & filters.private)
async def about_command(client, message: Message):
    # Store the original message ID
    original_message_id = message.id

    # Delete only the user's command message
    try:
        await client.delete_messages(
            chat_id=message.chat.id, 
            message_ids=[original_message_id]
        )
    except Exception:
        pass

    # Create keyboard for about
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🏠 Back to Start", callback_data="start")
        ]
    ])
    
    # Send about message
    await client.send_message(
        chat_id=message.chat.id,
        text=ABOUT_TEXT,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.command(["start"]) & filters.private)
async def start_command(client, message: Message):
    # Store the original message ID
    original_message_id = message.id

    # Delete only the user's command message
    try:
        await client.delete_messages(
            chat_id=message.chat.id, 
            message_ids=[original_message_id]
        )
    except Exception:
        pass

    status, storage, features = await get_user_info(message.from_user.id)
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            InlineKeyboardButton("❓ Help", callback_data="help")
        ],
        [
            InlineKeyboardButton("🤖 About", callback_data="about")
        ],
        [
            InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
        ]
    ])
    
    # Send the response and store the bot's message
    await client.send_message(
        chat_id=message.chat.id,
        text=START_TEXT.format(
            status=status,
            storage=storage,
            features=features
        ),
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    """Handle all inline button callbacks"""
    try:
        data = callback_query.data
        message = callback_query.message
        
        # Always answer the callback query to remove loading state
        await callback_query.answer()
        
        # Direct link download handler
        if data.startswith("default|") or data.startswith("rename|"):
            file_id = data.split("|")[1]
            
            if data.startswith("default|"):
                # Quick download
                url = pending_downloads.get(file_id)
                if not url:
                    await message.edit_text("❌ Download link expired. Please try again.")
                    return
                
                await handle_download(client, message, url)
                del pending_downloads[file_id]
            
            elif data.startswith("rename|"):
                # Custom name
                pending_renames[message.chat.id] = {
                    "type": "direct",
                    "url": pending_downloads.get(file_id)
                }
                await message.edit_text(
                    "📝 **Send me a custom file name**\n\n"
                    "• Send the name you want (without extension)\n"
                    "• Or send /cancel to abort"
                )
            
            return
        
        # YouTube download handler
        if data.startswith("ytdl|"):
            parts = data.split("|")
            if len(parts) == 3:
                url = parts[1]
                download_type = parts[2]
                
                if download_type == "default":
                    # Quick download (video)
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("🎥 Video", callback_data=f"ytdl_video|{url}"),
                            InlineKeyboardButton("🎵 Audio", callback_data=f"ytdl_audio|{url}")
                        ],
                        [
                            InlineKeyboardButton("❌ Cancel", callback_data="cancel")
                        ]
                    ])
                    
                    await message.edit_text(
                        "**Choose Download Type:**", 
                        reply_markup=keyboard
                    )
                elif download_type == "rename":
                    # Custom name for YouTube download
                    pending_renames[callback_query.from_user.id] = {
                        "type": "youtube",
                        "url": url
                    }
                    await message.edit_text(
                        "📝 **Send me a custom file name**\n\n"
                        "• Send the name you want (without extension)\n"
                        "• Or send /cancel to abort"
                    )
            return
        
        # YouTube video and audio download
        if data.startswith("ytdl_video|") or data.startswith("ytdl_audio|"):
            url = data.split("|")[1]
            
            if data.startswith("ytdl_video|"):
                # Trigger video download
                await callback_query.message.reply_to_message.delete()
                await callback_query.message.delete()
                
                ydl_opts = {
                    "format": "best[ext=mp4]",
                    "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                    "writethumbnail": True,
                }
                
                with YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                    await download_youtube(client, callback_query.message, url, "video")
            
            elif data.startswith("ytdl_audio|"):
                # Trigger audio download
                await callback_query.message.reply_to_message.delete()
                await callback_query.message.delete()
                
                ydl_opts = {
                    "format": "bestaudio",
                    "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                    "writethumbnail": True,
                }
                
                with YoutubeDL(ydl_opts) as ydl:
                    info_dict = ydl.extract_info(url, download=False)
                    await download_youtube(client, callback_query.message, url, "audio")
            
            return
        
        # Cancel button handler
        if data == "cancel":
            await message.edit_text("❌ **Download cancelled**")
            return
        
        # Existing callback handlers
        if data == "start":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                    InlineKeyboardButton("❓ Help", callback_data="help")
                ],
                [
                    InlineKeyboardButton("🤖 About", callback_data="about")
                ],
                [
                    InlineKeyboardButton("💫 Support", url="https://t.me/your_support")
                ]
            ])
            
            await message.edit_text(
                START_TEXT.format(callback_query.from_user.first_name),
                reply_markup=keyboard
            )
        
    except Exception as e:
        logging.error(f"Callback handler error: {str(e)}")
        await message.reply_text("❌ An error occurred. Please try again.")

async def broadcast_handler(client, message: Message):
    """
    Handle broadcast messages from the bot owner
    Only the owner can use this command
    """
    # Check if the user is the owner
    if message.from_user.id != OWNER_ID:
        await message.reply_text("❌ You are not authorized to use this command.")
        return

    # Check if the message is a reply to another message
    if not message.reply_to_message:
        await message.reply_text("❌ Please reply to a message you want to broadcast.")
        return

    # Get the message to broadcast
    broadcast_msg = message.reply_to_message

    # Send a progress message
    status_msg = await message.reply_text("🔄 Starting broadcast...")

    # Track broadcast statistics
    total_users = 0
    successful_broadcasts = 0
    failed_broadcasts = 0
    blocked_users = 0

    # Get all users from the database (assuming you have a method to retrieve users)
    try:
        users = await get_all_users()  # You'll need to implement this function
    except Exception as e:
        await status_msg.edit_text(f"❌ Error retrieving users: {str(e)}")
        return

    # Broadcast the message
    for user_id in users:
        try:
            # Try to send the message
            if broadcast_msg.text:
                await client.send_message(
                    chat_id=user_id, 
                    text=broadcast_msg.text
                )
            elif broadcast_msg.caption:
                # If it's a media message with a caption
                await client.copy_message(
                    chat_id=user_id,
                    from_chat_id=broadcast_msg.chat.id,
                    message_id=broadcast_msg.id
                )
            
            successful_broadcasts += 1
        except FloodWait as e:
            # Handle Telegram's flood wait
            await asyncio.sleep(e.x)
            try:
                if broadcast_msg.text:
                    await client.send_message(
                        chat_id=user_id, 
                        text=broadcast_msg.text
                    )
                elif broadcast_msg.caption:
                    await client.copy_message(
                        chat_id=user_id,
                        from_chat_id=broadcast_msg.chat.id,
                        message_id=broadcast_msg.id
                    )
                successful_broadcasts += 1
            except Exception:
                failed_broadcasts += 1
        except Exception as e:
            # Check for specific error types
            if "blocked" in str(e).lower():
                blocked_users += 1
            failed_broadcasts += 1

        total_users += 1

    # Update status message with broadcast results
    await status_msg.edit_text(
        f"📊 **Broadcast Complete**\n\n"
        f"Total Users: `{total_users}`\n"
        f"Successful: `{successful_broadcasts}`\n"
        f"Failed: `{failed_broadcasts}`\n"
        f"Blocked Users: `{blocked_users}`"
    )

# Placeholder function for getting all users
async def get_all_users():
    """
    Retrieve all user IDs from the database
    This is a placeholder and should be replaced with actual database logic
    """
    # In a real implementation, this would query your database
    # For now, we'll return an empty list to prevent errors
    return []

@bot.on_message(filters.command(["broadcast"]) & filters.user(OWNER_ID))
async def broadcast_message(client, message: Message):
    """
    Command handler for broadcast
    Checks user permissions and calls broadcast_handler
    """
    await broadcast_handler(client, message)

@bot.on_message(filters.private & filters.text)
async def handle_message(client, message):
    text = message.text
    chat_id = message.chat.id
    
    if text.startswith("/"):
        return
        
    if chat_id in pending_renames:
        if text.lower() == "/cancel":
            pending_renames.pop(chat_id)
            await message.reply_text("❌ Process Cancelled")
            return
            
        rename_info = pending_renames.pop(chat_id)
        if rename_info.get("type") == "youtube":
            await download_youtube(client, message, rename_info["url"], text)
        else:
            await handle_download(client, message, rename_info["url"], text)
        return
        
    if re.match(YOUTUBE_REGEX, text):
        await process_youtube(client, message, text)
    elif re.match(URL_REGEX, text):
        # Get file size
        file_size = await get_file_size(text)
        
        # Check file size (2GB limit)
        if file_size > 2 * 1024 * 1024 * 1024:  # 2GB in bytes
            await message.reply_text(
                f"❌ **File size ({humanbytes(file_size)}) is too large!**\n\n"
                "Maximum allowed size is 2GB"
            )
            return
        
        file_id = str(uuid.uuid4())
        pending_downloads[file_id] = text
        
        original_filename = await get_filename(text) or "File"
        size_text = humanbytes(file_size) if file_size else "Unknown"
        
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
            f"**🔗 URL Detected!**\n\n"
            f"📦 **File Size:** {size_text}\n"
            f"📄 **Original Name:** `{original_filename}`\n"
            f"🎯 **Choose an option:**",
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
