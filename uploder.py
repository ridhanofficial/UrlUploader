import os
import re
import uuid
import time
import logging
import asyncio
import math

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

import yt_dlp
import aiohttp

# Import config variables directly
from config import (
    API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, 
    OWNER_ID, MAX_FILE_SIZE, DOWNLOAD_LOCATION
)

# Define thumbnail location
THUMB_LOCATION = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thumb")

# Utility functions
from plugins.utils import get_filename, get_file_size, file_size_format
from helpers.utils import async_download_file

# Ensure thumbnail directory exists
os.makedirs(THUMB_LOCATION, exist_ok=True)

# Define text constants
START_TEXT = """
👋 **Welcome {name} to URL Uploader Bot!**

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
📥 **File Upload Commands**
• Send me a direct link to upload a file
• Send a YouTube link to download video/audio

🎛️ **Available Features**
• Direct file upload
• YouTube video download
• YouTube audio download
• Custom file naming
• Thumbnail support

📝 **How to Use**
1. Send a direct download link
2. Send a YouTube video link
3. Choose download options
4. Customize file name if needed

❓ **Need More Help?**
Contact @your_support_username
"""

ABOUT_TEXT = """
🤖 **Bot Details**
• Version: 2.0
• Language: Python
• Library: Pyrogram

👨‍💻 **Developer**
• @your_username

🔗 **Source Code**
• Available on request
"""

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
        
        # Extract info with yt-dlp to get detailed format information
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        
        # Get full video information
        full_info = yt_dlp.YoutubeDL().extract_info(url, download=False)
        
        # Prepare video qualities keyboard
        video_buttons = []
        current_row = []
        
        # Filter and sort video formats
        video_formats = [
            f for f in full_info.get('formats', []) 
            if f.get('height') and f.get('ext') == 'mp4'
        ]
        
        # Sort formats by resolution
        video_formats.sort(key=lambda x: x.get('height', 0), reverse=True)
        
        # Create buttons for unique resolutions
        seen_resolutions = set()
        for fmt in video_formats:
            resolution = f"{fmt.get('height', 0)}p"
            if resolution not in seen_resolutions:
                seen_resolutions.add(resolution)
                current_row.append(
                    InlineKeyboardButton(
                        f"🎥 {resolution}", 
                        callback_data=f"ytdl_video_quality|{url}|{fmt.get('format_id', '')}"
                    )
                )
                
                # Create rows of 2 buttons
                if len(current_row) == 2:
                    video_buttons.append(current_row)
                    current_row = []
        
        # Add any remaining buttons
        if current_row:
            video_buttons.append(current_row)
        
        # Add additional rows
        video_buttons.extend([
            [
                InlineKeyboardButton("🎵 Audio", callback_data=f"ytdl_audio|{url}"),
                InlineKeyboardButton("✏️ Custom Name", callback_data=f"ytdl|{url}|rename")
            ],
            [
                InlineKeyboardButton("❌ Cancel", callback_data="cancel")
            ]
        ])
        
        keyboard = InlineKeyboardMarkup(video_buttons)
        
        # Prepare video details
        title = full_info.get('title', 'Unknown Title')
        duration = full_info.get('duration', 0)
        uploader = full_info.get('uploader', 'Unknown Uploader')
        
        await progress_msg.edit_text(
            f"**🎥 YouTube Video Detected!**\n\n"
            f"📹 **Title:** `{title}`\n"
            f"👤 **Uploader:** `{uploader}`\n"
            f"⏱️ **Duration:** {duration} seconds\n"
            f"🎯 **Choose Download Quality:**",
            reply_markup=keyboard
        )
    
    except Exception as e:
        logging.error(f"YouTube processing error: {str(e)}")
        await progress_msg.edit_text(f"❌ **Failed to process YouTube video:** {str(e)}")

async def get_max_file_size(user_id: int) -> int:
    return MAX_FILE_SIZE

async def get_concurrent_downloads(user_id: int) -> int:
    return 5

async def save_thumb(user_id: int, thumb_path: str):
    """
    Save user's custom thumbnail
    
    :param user_id: Telegram user ID
    :param thumb_path: Path to the thumbnail image
    """
    # Ensure thumb directory exists
    os.makedirs(THUMB_LOCATION, exist_ok=True)
    
    # Destination path for thumbnail
    dest_path = os.path.join(THUMB_LOCATION, f"{user_id}.jpg")
    
    # Copy or move the thumbnail
    try:
        import shutil
        shutil.copy2(thumb_path, dest_path)
    except Exception as e:
        logging.error(f"Error saving thumbnail: {e}")
        raise

async def get_thumb(user_id: int):
    """
    Get user's custom thumbnail or default thumbnail
    
    :param user_id: Telegram user ID
    :return: Path to thumbnail or None
    """
    # Check for user's custom thumbnail
    custom_thumb_path = os.path.join(THUMB_LOCATION, f"{user_id}.jpg")
    if os.path.exists(custom_thumb_path):
        return custom_thumb_path
    
    # Check for default thumbnail
    default_thumb_path = os.path.join(THUMB_LOCATION, "default.jpg")
    if os.path.exists(default_thumb_path):
        return default_thumb_path
    
    return None

async def delete_thumb(user_id: int):
    """
    Delete user's custom thumbnail
    
    :param user_id: Telegram user ID
    """
    thumb_path = os.path.join(THUMB_LOCATION, f"{user_id}.jpg")
    
    if os.path.exists(thumb_path):
        try:
            os.remove(thumb_path)
            return True
        except Exception as e:
            logging.error(f"Error deleting thumbnail: {e}")
            return False
    
    return False

async def send_file_with_thumbnail(client, chat_id, document, file_name, caption, progress, progress_args):
    """Send file with user's thumbnail if available"""
    thumb = await get_thumb(chat_id)
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
    
    if round(diff % 3.0) == 0 or current == total:
        # Calculate speed and progress
        speed = current / diff if diff > 0 else 0
        percentage = (current * 100) / total if total > 0 else 0
        
        # Format progress bar
        progress_size = 20
        filled = int(percentage / (100/progress_size))
        bar = "█" * filled + "░" * (progress_size - filled)
        
        # Format text
        text = (
            f"{ud_type}\n\n"
            f"**Progress:** {bar}\n"
            f"**Completed:** {humanbytes(current)} of {humanbytes(total)}\n"
            f"**Speed:** {humanbytes(speed)}/s\n"
            f"**ETA:** {TimeFormatter((total-current)/speed if speed > 0 else 0)}\n"
        )
        
        try:
            await message.edit_text(text)
        except:
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
            name=message.from_user.first_name,
            status=status,
            storage=storage,
            features=features
        ),
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    try:
        data = callback_query.data
        message = callback_query.message
        
        # Always answer callback query first
        await callback_query.answer("Processing...")
        
        if data == "cancel":
            await message.edit_text("❌ **Process Cancelled**")
            return
            
        if data.startswith(("default|", "rename|")):
            file_id = data.split("|")[1]
            url = pending_downloads.get(file_id)
            
            if not url:
                await message.edit_text("❌ Link expired. Please send the URL again.")
                return
                
            if data.startswith("default|"):
                await message.edit_text("🔄 **Starting Download...**")
                
                try:
                    # Get file info
                    filename = await get_filename(url)
                    file_size = await get_file_size(url)
                    
                    # Show download status
                    status_msg = await message.reply_text(
                        f"📥 **Downloading File**\n\n"
                        f"**File:** `{filename}`\n"
                        f"**Size:** {humanbytes(file_size)}\n\n"
                        "**Status:** Starting download..."
                    )
                    
                    # Download file with progress
                    downloaded_file = await async_download_file(
                        url=url,
                        filename=filename,
                        progress=progress_for_pyrogram,
                        progress_args=(status_msg, time.time())
                    )
                    
                    # Upload file
                    await send_file_with_thumbnail(
                        client,
                        message.chat.id,
                        downloaded_file,
                        filename,
                        f"📤 **Upload Complete!**\n\n**Filename:** `{filename}`",
                        progress_for_pyrogram,
                        (status_msg, time.time())
                    )
                    
                    # Cleanup
                    try:
                        os.remove(downloaded_file)
                        await message.delete()
                    except:
                        pass
                        
                except Exception as e:
                    await status_msg.edit_text(f"❌ **Download Failed!**\n\n`{str(e)}`")
                    
                finally:
                    if file_id in pending_downloads:
                        del pending_downloads[file_id]
                        
            elif data.startswith("rename|"):
                pending_renames[message.chat.id] = {
                    "url": url,
                    "type": "direct"
                }
                await message.edit_text(
                    "✏️ **Send me the new file name**\n\n"
                    "• Without extension\n"
                    "• Send /cancel to cancel"
                )
                
        elif data.startswith("ytdl_"):
            # Handle YouTube download options
            if data.startswith("ytdl_video_quality|"):
                url, quality = data.split("|")[1:]
                await download_youtube(client, message, url, "video", quality)
                
            elif data.startswith("ytdl_audio|"):
                url = data.split("|")[1]
                await download_youtube(client, message, url, "audio")
                
    except Exception as e:
        try:
            await message.edit_text(f"❌ **Error:** `{str(e)}`")
        except:
            pass

async def download_youtube(client, progress_msg, url, download_type="video", quality=None):
    """
    Download YouTube video or audio using yt-dlp
    
    :param client: Pyrogram client
    :param progress_msg: Progress message to update
    :param url: YouTube URL
    :param download_type: 'video' or 'audio'
    :param quality: Specific quality format ID for video
    """
    try:
        # Prepare download options based on type
        if download_type == "video":
            ydl_opts = {
                "format": quality or "best[ext=mp4]",
                "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                "writethumbnail": True,
            }
        else:  # audio
            ydl_opts = {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                "writethumbnail": True,
            }
        
        # Extract video information
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            # Update progress message with video details
            title = info_dict.get('title', 'Unknown Title')
            uploader = info_dict.get('uploader', 'Unknown Uploader')
            duration = info_dict.get('duration', 0)
            
            await progress_msg.edit_text(
                f"📥 **Downloading {download_type.capitalize()}...**\n\n"
                f"📹 **Title:** `{title}`\n"
                f"👤 **Uploader:** `{uploader}`\n"
                f"⏱️ **Duration:** {duration} seconds"
            )
            
            # Download the file
            downloaded_file = ydl.download([url])[0]
        
        # Prepare file for upload
        if download_type == "video":
            # Find the video file
            video_file = [f for f in os.listdir() if f.endswith('.mp4')][0]
            
            # Get thumbnail
            thumbnail_url = info_dict.get('thumbnail')
            thumbnail_file = None
            if thumbnail_url:
                try:
                    thumbnail_file = f"{os.path.splitext(video_file)[0]}.jpg"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(thumbnail_url) as resp:
                            if resp.status == 200:
                                with open(thumbnail_file, 'wb') as f:
                                    f.write(await resp.read())
                except Exception as e:
                    logging.error(f"Thumbnail download error: {e}")
                    thumbnail_file = None
            
            # Upload video
            await progress_msg.edit_text(f"📤 **Uploading Video:** `{title}`")
            await client.send_video(
                progress_msg.chat.id,
                video_file,
                caption=f"🎥 {title}",
                duration=duration,
                thumb=thumbnail_file,
                progress=progress_for_pyrogram,
                progress_args=(progress_msg, "Uploading", time.time())
            )
            
            # Clean up files
            os.remove(video_file)
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
        
        else:  # audio
            # Find the audio file
            audio_file = [f for f in os.listdir() if f.endswith('.mp3')][0]
            
            # Get thumbnail
            thumbnail_url = info_dict.get('thumbnail')
            thumbnail_file = None
            if thumbnail_url:
                try:
                    thumbnail_file = f"{os.path.splitext(audio_file)[0]}.jpg"
                    async with aiohttp.ClientSession() as session:
                        async with session.get(thumbnail_url) as resp:
                            if resp.status == 200:
                                with open(thumbnail_file, 'wb') as f:
                                    f.write(await resp.read())
                except Exception as e:
                    logging.error(f"Thumbnail download error: {e}")
                    thumbnail_file = None
            
            # Upload audio
            await progress_msg.edit_text(f"📤 **Uploading Audio:** `{title}`")
            await client.send_audio(
                progress_msg.chat.id,
                audio_file,
                caption=f"🎵 {title}",
                duration=duration,
                thumb=thumbnail_file,
                progress=progress_for_pyrogram,
                progress_args=(progress_msg, "Uploading", time.time())
            )
            
            # Clean up files
            os.remove(audio_file)
            if thumbnail_file and os.path.exists(thumbnail_file):
                os.remove(thumbnail_file)
        
        # Delete progress message
        await progress_msg.delete()
    
    except Exception as e:
        logging.error(f"YouTube download error: {str(e)}")
        await progress_msg.edit_text(f"❌ **Download failed:** {str(e)}")
        raise

async def async_download_file(url, filename, progress=None, progress_args=None):
    """Download file with better progress updates"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    raise Exception(f"Failed to download: HTTP {response.status}")
                
                # Get file size
                file_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                start_time = time.time()
                
                with open(filename, 'wb') as f:
                    async for chunk in response.content.iter_chunked(1024*8):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress and progress_args:
                                await progress(
                                    downloaded,
                                    file_size,
                                    "📥 Downloading",
                                    progress_args[0],
                                    start_time
                                )
                return filename
                
    except Exception as e:
        if os.path.exists(filename):
            os.remove(filename)
        raise Exception(f"Download failed: {str(e)}")

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

@bot.on_message(filters.command(["thumb"]) & filters.private)
async def save_thumbnail(client, message: Message):
    """
    Handle thumbnail saving command
    """
    if not message.reply_to_message or not message.reply_to_message.photo:
        await message.reply_text("❌ Please reply to a photo to set as thumbnail.")
        return
    
    try:
        # Download the photo
        thumb = await client.download_media(message.reply_to_message.photo)
        
        # Save the thumbnail
        await save_thumb(message.from_user.id, thumb)
        
        # Remove temporary downloaded file
        os.remove(thumb)
        
        await message.reply_text("✅ Thumbnail saved successfully!")
    
    except Exception as e:
        logging.error(f"Thumbnail save error: {e}")
        await message.reply_text("❌ Failed to save thumbnail. Please try again.")

@bot.on_message(filters.command(["delthumb"]) & filters.private)
async def delete_thumbnail(client, message: Message):
    """
    Handle thumbnail deletion command
    """
    result = await delete_thumb(message.from_user.id)
    
    if result:
        await message.reply_text("✅ Thumbnail deleted successfully!")
    else:
        await message.reply_text("❌ No custom thumbnail found.")
