import os
import re
import uuid
import time
import logging
import asyncio
import math

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
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
👋 Hi {first_name}, I'm a Telegram File Uploader Bot!

Status: {status}
Storage: {storage}
Features: {features}

I can help you:
• Upload files from direct links
• Download YouTube videos and audio
• Customize file names
• And much more!

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
    """
    Download a file using aiohttp with progress tracking
    
    :param url: URL of the file to download
    :param filename: Name of the file to save
    :param progress: Optional progress callback function
    :param progress_args: Optional arguments for progress callback
    :return: Path to the downloaded file
    """
    download_directory = "Download"
    os.makedirs(download_directory, exist_ok=True)
    
    file_path = os.path.join(download_directory, filename)
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Download failed with status {response.status}")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0
            
            with open(file_path, "wb") as file:
                async for chunk in response.content.iter_chunked(1024):
                    file.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # Call progress callback if provided
                    if progress and progress_args:
                        try:
                            await progress(downloaded_size, total_size, *progress_args)
                        except Exception as e:
                            logging.error(f"Progress callback error: {e}")
    
    return file_path

async def send_file_with_thumbnail(client, chat_id, document, file_name, caption, progress=None, progress_args=None):
    """
    Send file with user's thumbnail if available
    
    :param client: Pyrogram client
    :param chat_id: Destination chat ID
    :param document: Path to the document
    :param file_name: Name of the file
    :param caption: Caption for the file
    :param progress: Optional progress callback function
    :param progress_args: Optional arguments for progress callback
    :return: Sent message
    """
    try:
        # Try to get user's custom thumbnail
        thumb = await get_thumb(chat_id)
        
        # Send the file
        sent_message = await client.send_document(
            chat_id=chat_id,
            document=document,
            file_name=file_name,
            caption=caption,
            thumb=thumb,
            progress=progress,
            progress_args=progress_args
        )
        
        return sent_message
    
    except Exception as e:
        logging.error(f"Error sending file: {str(e)}")
        raise

async def handle_download_or_upload(client, message, url, filename=None, download_type="direct"):
    """
    Unified handler for downloading and uploading files
    
    :param client: Pyrogram client
    :param message: Original message
    :param url: URL to download from
    :param filename: Optional custom filename
    :param download_type: Type of download (direct/youtube)
    """
    try:
        # Initial progress message
        progress_msg = await message.reply_text(
            "⏳ **Initializing Download...**\n\n"
            "• Please wait while I process your request\n"
            "• You'll see progress updates here"
        )
        
        start_time = time.time()
        
        # Determine filename if not provided
        if not filename:
            filename = await get_filename(url) or "file"
        
        # Get file size
        file_size = await get_file_size(url)
        
        # Update status with file info
        await progress_msg.edit_text(
            f"📥 **Starting Download...**\n\n"
            f"**File:** `{filename}`\n"
            f"**Size:** {humanbytes(file_size)}\n\n"
            "**Status:** Downloading..."
        )
        
        # Download file
        file_path = await async_download_file(
            url=url,
            filename=filename,
            progress=progress_for_pyrogram,
            progress_args=(progress_msg, start_time)
        )
        
        # Upload file
        sent_file = await send_file_with_thumbnail(
            client=client,
            chat_id=message.chat.id,
            document=file_path,
            file_name=filename,
            caption=f"📤 **Upload Complete!**\n\n**Filename:** `{filename}`",
            progress=progress_for_pyrogram,
            progress_args=(progress_msg, start_time)
        )
        
        # Delete progress message
        try:
            await progress_msg.delete()
        except Exception as e:
            logging.error(f"Error deleting progress message: {str(e)}")
        
        # Cleanup downloaded file
        try:
            os.remove(file_path)
        except Exception as e:
            logging.error(f"Error removing file: {str(e)}")
        
        return sent_file
    
    except Exception as e:
        # Handle and log any errors during download/upload
        error_msg = str(e)
        try:
            await progress_msg.edit_text(f"❌ **Process Failed!**\n\n`{error_msg}`")
        except:
            await message.reply_text(f"❌ **Process Failed!**\n\n`{error_msg}`")
        
        logging.error(f"Download/Upload Error: {error_msg}")
        return None

def progress_for_pyrogram(current, total, ud_type, message, start):
    """
    Custom progress callback for file uploads and downloads
    
    :param current: Current progress
    :param total: Total file size
    :param ud_type: Upload/Download type
    :param message: Telegram message to update
    :param start: Start time of the operation
    """
    now = time.time()
    diff = now - start
    
    if current == total:
        # Operation completed
        return
    
    if round(diff % 10.00) == 0 or current == total:
        # Calculate progress percentage
        percentage = current * 100 / total
        
        # Calculate speed
        speed = current / diff if diff > 0 else 0
        speed_str = humanbytes(speed) + "/s"
        
        # Calculate ETA
        eta = int((total - current) / speed) if speed > 0 else 0
        eta_str = TimeFormatter(eta * 1000)
        
        # Create progress bar
        progress_bar_length = 15
        filled_length = int(progress_bar_length * current // total)
        progress_bar = '█' * filled_length + '░' * (progress_bar_length - filled_length)
        
        # Prepare status message
        status_msg = (
            f"**{ud_type.capitalize()}ing File**\n\n"
            f"📊 Progress: `{progress_bar}` {percentage:.1f}%\n"
            f"📥 Downloaded: `{humanbytes(current)}` of `{humanbytes(total)}`\n"
            f"🚀 Speed: `{speed_str}`\n"
            f"⏱️ ETA: `{eta_str}`"
        )
        
        try:
            # Update message every 10 seconds or when complete
            if current != total:
                # Edit message with progress
                message.edit_text(status_msg)
            else:
                # When download/upload is complete
                message.edit_text(
                    f"**✅ {ud_type.capitalize()} Complete!**\n"
                    f"📦 Total Size: `{humanbytes(total)}`\n"
                    f"⏱️ Time Taken: `{TimeFormatter((now - start) * 1000)}`"
                )
        except FloodWait as e:
            # Handle Telegram's flood wait
            asyncio.sleep(e.x)
        except Exception as e:
            # Log any other exceptions
            logging.error(f"Progress update error: {str(e)}")

def TimeFormatter(milliseconds: int) -> str:
    """
    Convert milliseconds to human-readable time format
    
    :param milliseconds: Time in milliseconds
    :return: Formatted time string
    """
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    # Format the time components
    time_str = []
    if days > 0:
        time_str.append(f"{days}d")
    if hours > 0:
        time_str.append(f"{hours}h")
    if minutes > 0:
        time_str.append(f"{minutes}m")
    if seconds > 0:
        time_str.append(f"{seconds}s")
    
    return " ".join(time_str) if time_str else "0s"

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

# Initialize bot with proper settings
bot = Client(
    "uploader_bot", 
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=2,  # Reduced workers to prevent overload
    parse_mode="Markdown"
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
            first_name=message.from_user.first_name,
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
        # Log the callback data for debugging
        logging.info(f"Received callback data: {callback_query.data}")
        
        data = callback_query.data
        message = callback_query.message
        chat_id = message.chat.id
        
        # Always answer the callback query to prevent hanging
        await callback_query.answer(
            "Processing your request...",
            show_alert=False
        )
        
        # Comprehensive callback handling
        if data == "start":
            # Start menu
            status, storage, features = await get_user_info(callback_query.from_user.id)
            
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                    InlineKeyboardButton("❓ Help", callback_data="help")
                ],
                [
                    InlineKeyboardButton("🤖 About", callback_data="about")
                ],
                [
                    InlineKeyboardButton("💫 Support", url="https://t.me/your_support_group")
                ]
            ])
            
            await message.edit_text(
                START_TEXT.format(
                    first_name=callback_query.from_user.first_name,
                    status=status,
                    storage=storage,
                    features=features
                ),
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        
        elif data == "help":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]
            ])
            
            await message.edit_text(
                HELP_TEXT,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        
        elif data == "about":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]
            ])
            
            await message.edit_text(
                ABOUT_TEXT,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
        
        elif data == "settings":
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🏠 Back to Start", callback_data="start")
                ]
            ])
            
            await message.edit_text(
                "**⚙️ Settings**\n\nNo settings configured yet.",
                reply_markup=keyboard
            )
        
        # Handling download and rename buttons
        elif data.startswith("default|"):
            file_id = data.split("|")[1]
            url = pending_downloads.get(file_id)
            
            if not url:
                await callback_query.answer("❌ Link expired. Please send the URL again.", show_alert=True)
                return
            
            # Use the new unified download handler
            await handle_download_or_upload(client, message, url)
        
        elif data.startswith("rename|"):
            file_id = data.split("|")[1]
            url = pending_downloads.get(file_id)
            
            if not url:
                await callback_query.answer("❌ Link expired. Please send the URL again.", show_alert=True)
                return
            
            # Prompt for new filename
            await message.edit_text(
                "✏️ **Send me the new file name**\n\n"
                "• Send name without extension\n"
                "• Or /cancel to abort"
            )
            pending_renames[chat_id] = {"url": url, "type": "direct"}
        
        elif data.startswith("cancel"):
            # Cancel download or rename
            await message.edit_text("❌ **Process Cancelled**")
        
        else:
            # Unknown callback data
            await callback_query.answer("❌ Invalid button.", show_alert=True)
    
    except Exception as e:
        logging.error(f"Callback Handler Error: {str(e)}")
        try:
            await message.edit_text(f"❌ An error occurred: {str(e)}")
        except:
            await callback_query.answer(f"❌ An error occurred: {str(e)}", show_alert=True)

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
            await handle_download_or_upload(client, message, rename_info["url"], text)
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

async def download_youtube(client, progress_msg, url, download_type="video"):
    """
    Download YouTube video or audio using yt-dlp
    
    :param client: Pyrogram client
    :param progress_msg: Progress message to update
    :param url: YouTube URL
    :param download_type: 'video' or 'audio'
    """
    try:
        # Prepare download options based on type
        if download_type == "video":
            ydl_opts = {
                "format": "best[ext=mp4]",
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
            
            # Modify progress message
            await progress_msg.edit_text(
                f"🎬 **YouTube {download_type.capitalize()}**\n\n"
                f"**Title:** `{title}`\n"
                f"**Uploader:** `{uploader}`\n"
                "**Status:** Preparing download..."
            )
            
            # Download the file
            ydl_opts['outtmpl'] = os.path.join(DOWNLOAD_LOCATION, ydl_opts['outtmpl'])
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                file_path = ydl.download([url])[0]
            
            # Get the actual downloaded file path
            if isinstance(file_path, list):
                file_path = file_path[0]
            
            # Send the file using the unified handler
            sent_file = await send_file_with_thumbnail(
                client=client,
                chat_id=progress_msg.chat.id,
                document=file_path,
                file_name=os.path.basename(file_path),
                caption=f"**📥 YouTube {download_type.capitalize()}**\n\n"
                        f"**Title:** `{title}`\n"
                        f"**Uploader:** `{uploader}`"
            )
            
            # Delete progress message
            try:
                await progress_msg.delete()
            except Exception as e:
                logging.error(f"Error deleting progress message: {str(e)}")
            
            # Cleanup downloaded file
            try:
                os.remove(file_path)
            except Exception as e:
                logging.error(f"Error removing file: {str(e)}")
            
            return sent_file
    
    except Exception as e:
        error_msg = str(e)
        try:
            await progress_msg.edit_text(f"❌ **Download Failed!**\n\n`{error_msg}`")
        except:
            await progress_msg.reply_text(f"❌ **Download Failed!**\n\n`{error_msg}`")
        
        logging.error(f"YouTube Download Error: {error_msg}")
        return None

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
