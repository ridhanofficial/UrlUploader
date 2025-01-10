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
    OWNER_ID, MAX_FILE_SIZE, DOWNLOAD_LOCATION,
    THUMB_LOCATION
)

# Utility functions
from plugins.utils import get_filename, get_file_size, file_size_format
from helpers.utils import async_download_file

# Ensure thumbnail directory exists
os.makedirs(THUMB_LOCATION, exist_ok=True)

# Define text constants
START_TEXT = """
👋 Hi {}, I'm a Telegram File Uploader Bot!

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
                
                # Create a new progress message
                progress_msg = await message.reply_text("📥 **Downloading file...**")
                
                try:
                    # Get filename from URL
                    filename = await get_filename(url) or "downloaded_file"
                    
                    # Download file
                    file_path = await async_download_file(
                        url, 
                        filename, 
                        progress=progress_for_pyrogram, 
                        progress_args=(progress_msg, "Downloading", time.time())
                    )
                    
                    # Send file with thumbnail
                    await send_file_with_thumbnail(
                        client, 
                        message.chat.id, 
                        file_path, 
                        filename, 
                        caption="📥 File Downloaded", 
                        progress=progress_for_pyrogram, 
                        progress_args=(progress_msg, "Uploading", time.time())
                    )
                    
                    # Clean up
                    os.remove(file_path)
                    del pending_downloads[file_id]
                    await progress_msg.delete()
                
                except Exception as e:
                    await progress_msg.edit_text(f"❌ **Download failed:** {str(e)}")
                    logging.error(f"Direct download error: {str(e)}")
            
            elif data.startswith("rename|"):
                # Custom name
                url = pending_downloads.get(file_id)
                if not url:
                    await message.edit_text("❌ Download link expired. Please try again.")
                    return
                
                pending_renames[message.chat.id] = {
                    "type": "direct",
                    "url": url
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
                
                if download_type == "rename":
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
        
        # YouTube video download with quality selection
        if data.startswith("ytdl_video_quality|"):
            url, format_id = data.split("|")[1:]
            
            # Delete previous messages to clean up
            try:
                await message.reply_to_message.delete()
            except:
                pass
            
            try:
                await message.delete()
            except:
                pass
            
            # Trigger video download
            ydl_opts = {
                "format": format_id,
                "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                "writethumbnail": True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                
                # Create a new progress message
                progress_msg = await callback_query.message.reply_text("🎥 **Downloading Video...**")
                
                try:
                    await download_youtube(client, progress_msg, url, "video")
                except Exception as e:
                    await progress_msg.edit_text(f"❌ **Download failed:** {str(e)}")
            
            return
        
        # YouTube audio download
        if data.startswith("ytdl_audio|"):
            url = data.split("|")[1]
            
            # Delete previous messages to clean up
            try:
                await message.reply_to_message.delete()
            except:
                pass
            
            try:
                await message.delete()
            except:
                pass
            
            # Trigger audio download
            ydl_opts = {
                "format": "bestaudio",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }],
                "outtmpl": "%(title)s - %(extractor)s-%(id)s.%(ext)s",
                "writethumbnail": True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=False)
                
                # Create a new progress message
                progress_msg = await callback_query.message.reply_text("🎵 **Downloading Audio...**")
                
                try:
                    await download_youtube(client, progress_msg, url, "audio")
                except Exception as e:
                    await progress_msg.edit_text(f"❌ **Download failed:** {str(e)}")
            
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
