import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Outputs to console
        logging.FileHandler('bot.log')  # Outputs to a log file
    ]
)

import os
import re
import uuid
import time
import asyncio
import math
import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode

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
Hello {first_name}! 👋

**Status**: {status}
**Storage**: {storage}
**Features**: {features}

I'm a versatile URL Uploader Bot that can help you download and upload files from various sources!
"""

HELP_TEXT = """
**Bot Usage Guide** 📘

1. Send me a direct download link
2. Send me a YouTube video/audio link
3. Use inline buttons to customize download

**Supported Sources**:
• Direct Download Links
• YouTube Videos
• YouTube Audio
"""

ABOUT_TEXT = """
**URL Uploader Bot** 🤖

**Version**: 2.0
**Developer**: Your Name
**Language**: Python
**Library**: Pyrogram

A powerful Telegram bot designed to make file downloading and uploading seamless!
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

async def handle_download_or_upload(
    client, 
    message, 
    url, 
    download_type="default", 
    custom_filename=None
):
    """
    Unified handler for downloading and uploading files
    
    :param client: Pyrogram client
    :param message: Original message
    :param url: URL to download from
    :param download_type: Type of download (default/rename)
    :param custom_filename: Custom filename for the download
    :return: Path of downloaded file or None
    """
    try:
        # Generate a unique file ID
        file_id = str(uuid.uuid4())
        
        # Send initial progress message
        start_time = time.time()
        try:
            progress_msg = await message.reply_text(
                "🔄 **Preparing Download**...", 
                quote=True
            )
        except Exception as progress_msg_error:
            logging.warning(f"Could not send progress message: {progress_msg_error}")
            progress_msg = message
        
        # Determine filename
        if custom_filename:
            filename = f"{custom_filename}"
        else:
            # Extract filename from URL or generate a unique name
            filename = url.split('/')[-1] if url.split('/')[-1] else str(uuid.uuid4())
        
        # Sanitize filename
        filename = re.sub(r'[^\w\-_\. ]', '_', filename)
        
        # Ensure filename has an extension
        if '.' not in filename:
            filename += '.bin'  # Default extension if none exists
        
        try:
            # Attempt to get file size
            async with aiohttp.ClientSession() as session:
                async with session.head(url, allow_redirects=True) as response:
                    file_size = int(response.headers.get('Content-Length', 0))
        except Exception:
            file_size = 0
        
        # Download the file
        try:
            # Determine download method based on URL
            if "youtube.com" in url or "youtu.be" in url:
                # YouTube download
                downloaded_file = await download_youtube(
                    url, 
                    progress_msg, 
                    start_time, 
                    filename
                )
            else:
                # Direct download
                downloaded_file = await download_file(
                    url, 
                    filename, 
                    progress_msg, 
                    start_time, 
                    file_size
                )
            
            # Check if download was successful
            if not downloaded_file or not os.path.exists(downloaded_file):
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text("❌ **Download Failed**: Unable to download file")
                else:
                    await message.reply_text("❌ **Download Failed**: Unable to download file")
                return None
            
            # Upload the file
            try:
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text("📤 **Uploading File**...")
                
                # Get file size for upload progress
                upload_file_size = os.path.getsize(downloaded_file)
                
                # Determine file type for sending
                file_extension = os.path.splitext(downloaded_file)[1].lower()
                
                # Upload with progress tracking
                try:
                    if file_extension in ['.mp4', '.avi', '.mkv', '.mov', '.webm']:
                        # Video file
                        sent_file = await client.send_video(
                            chat_id=message.chat.id,
                            video=downloaded_file,
                            caption=f"📤 **Upload Complete!**\n\n**Filename:** `{os.path.basename(downloaded_file)}`",
                            progress=progress_for_pyrogram,
                            progress_args=(progress_msg, start_time, os.path.basename(downloaded_file), upload_file_size, "upload")
                        )
                    elif file_extension in ['.mp3', '.wav', '.flac', '.ogg']:
                        # Audio file
                        sent_file = await client.send_audio(
                            chat_id=message.chat.id,
                            audio=downloaded_file,
                            caption=f"📤 **Upload Complete!**\n\n**Filename:** `{os.path.basename(downloaded_file)}`",
                            progress=progress_for_pyrogram,
                            progress_args=(progress_msg, start_time, os.path.basename(downloaded_file), upload_file_size, "upload")
                        )
                    else:
                        # Generic document
                        sent_file = await client.send_document(
                            chat_id=message.chat.id,
                            document=downloaded_file,
                            caption=f"📤 **Upload Complete!**\n\n**Filename:** `{os.path.basename(downloaded_file)}`",
                            progress=progress_for_pyrogram,
                            progress_args=(progress_msg, start_time, os.path.basename(downloaded_file), upload_file_size, "upload")
                        )
                    
                    # Delete the progress message
                    if hasattr(progress_msg, 'delete'):
                        await progress_msg.delete()
                    
                    # Clean up the downloaded file
                    try:
                        os.remove(downloaded_file)
                    except Exception as cleanup_error:
                        logging.error(f"File cleanup error: {cleanup_error}")
                    
                    return downloaded_file
                
                except Exception as send_error:
                    logging.error(f"File Send Error: {send_error}")
                    if hasattr(progress_msg, 'edit_text'):
                        await progress_msg.edit_text(f"❌ **Upload Failed**: {str(send_error)}")
                    else:
                        await message.reply_text(f"❌ **Upload Failed**: {str(send_error)}")
                    return None
            
            except Exception as upload_error:
                logging.error(f"Upload Preparation Error: {upload_error}")
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text(f"❌ **Upload Preparation Failed**: {str(upload_error)}")
                else:
                    await message.reply_text(f"❌ **Upload Preparation Failed**: {str(upload_error)}")
                return None
        
        except Exception as download_error:
            logging.error(f"Download Error: {download_error}")
            if hasattr(progress_msg, 'edit_text'):
                await progress_msg.edit_text(f"❌ **Download Failed**: {str(download_error)}")
            else:
                await message.reply_text(f"❌ **Download Failed**: {str(download_error)}")
            return None
    
    except Exception as e:
        logging.error(f"General Download/Upload Error: {e}")
        try:
            await message.reply_text(f"❌ **Process Failed**: {str(e)}")
        except:
            pass
        return None

async def download_file(
    url, 
    filename, 
    progress_msg, 
    start_time, 
    file_size
):
    """
    Download a file from a direct URL with enhanced reliability
    
    :param url: Direct download URL
    :param filename: Name to save the file as
    :param progress_msg: Message to update progress
    :param start_time: Start time of download
    :param file_size: Total file size
    :return: Path to downloaded file
    """
    try:
        # Ensure downloads directory exists
        os.makedirs('downloads', exist_ok=True)
        
        # Full path for the file
        file_path = os.path.join('downloads', filename)
        
        # Timeout configuration
        timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout
        
        # Download the file with enhanced error handling
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.get(url, allow_redirects=True) as response:
                    # Check response status
                    if response.status not in [200, 206]:  # 200 OK or 206 Partial Content
                        if hasattr(progress_msg, 'edit_text'):
                            await progress_msg.edit_text(f"❌ **Download Failed**: HTTP {response.status}")
                        else:
                            await progress_msg.reply_text(f"❌ **Download Failed**: HTTP {response.status}")
                        return None
                    
                    # Update file size if not provided
                    if file_size == 0:
                        file_size = int(response.headers.get('Content-Length', 0))
                    
                    # Open file for writing using standard file operations
                    with open(file_path, 'wb') as f:
                        downloaded = 0
                        async for chunk in response.content.iter_chunked(64 * 1024):  # 64KB chunks
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Update progress
                            await progress_for_pyrogram(
                                downloaded, 
                                file_size, 
                                progress_msg, 
                                start_time, 
                                filename
                            )
                    
                    # Verify file size
                    actual_size = os.path.getsize(file_path)
                    if file_size > 0 and actual_size < file_size:
                        if hasattr(progress_msg, 'edit_text'):
                            await progress_msg.edit_text(f"❌ **Incomplete Download**: {actual_size}/{file_size} bytes")
                        else:
                            await progress_msg.reply_text(f"❌ **Incomplete Download**: {actual_size}/{file_size} bytes")
                        os.remove(file_path)
                        return None
                    
                    return file_path
            
            except (aiohttp.ClientError, asyncio.TimeoutError) as network_error:
                logging.error(f"Network Download Error: {network_error}")
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text(f"❌ **Network Error**: {str(network_error)}")
                else:
                    await progress_msg.reply_text(f"❌ **Network Error**: {str(network_error)}")
                return None
    
    except Exception as e:
        logging.error(f"Direct Download Error: {e}")
        if hasattr(progress_msg, 'edit_text'):
            await progress_msg.edit_text(f"❌ **Download Failed**: {str(e)}")
        else:
            await progress_msg.reply_text(f"❌ **Download Failed**: {str(e)}")
        return None

async def progress_for_pyrogram(
    current, 
    total, 
    message, 
    start_time, 
    file_name, 
    upload_type="download"
):
    """
    Advanced progress tracker with detailed bar and ETA
    
    :param current: Current progress
    :param total: Total file size
    :param message: Message to update
    :param start_time: Start time of download/upload
    :param file_name: Name of the file being processed
    :param upload_type: Type of operation (download/upload)
    """
    try:
        # Ensure upload_type is a string
        upload_type = str(upload_type).lower()
        
        now = time.time()
        diff = now - start_time
        
        if current == 0:
            return
        
        # Calculate speed
        speed = current / diff if diff > 0 else 0
        
        # Calculate ETA
        if speed > 0:
            time_to_complete = (total - current) / speed
            eta = datetime.timedelta(seconds=int(time_to_complete))
        else:
            eta = datetime.timedelta(seconds=0)
        
        # Calculate percentage
        percentage = current * 100 / total if total > 0 else 0
        
        # Create progress bar
        progress_bar_length = 20
        filled_length = int(progress_bar_length * current // total)
        bar = '█' * filled_length + '░' * (progress_bar_length - filled_length)
        
        # Format speed
        if speed > 1024 * 1024:
            speed_str = f"{speed / (1024 * 1024):.2f} MB/s"
        elif speed > 1024:
            speed_str = f"{speed / 1024:.2f} KB/s"
        else:
            speed_str = f"{speed:.2f} B/s"
        
        # Construct status message
        status_message = (
            f"**{upload_type.capitalize()} Progress** 📥\n"
            f"📁 **File**: `{file_name}`\n"
            f"🔢 **Progress**: [{bar}] {percentage:.2f}%\n"
            f"📊 **Size**: {humanbytes(current)} / {humanbytes(total)}\n"
            f"🚀 **Speed**: {speed_str}\n"
            f"⏳ **ETA**: {eta}"
        )
        
        # Update message every 5 seconds or at significant progress points
        if (now - getattr(progress_for_pyrogram, 'last_update', 0) > 5) or (current == total):
            try:
                if hasattr(message, 'edit_text'):
                    await message.edit_text(status_message)
                else:
                    await message.reply_text(status_message)
                progress_for_pyrogram.last_update = now
            except FloodWait as e:
                await asyncio.sleep(e.x)
            except Exception as edit_error:
                logging.error(f"Progress message update error: {edit_error}")
    
    except Exception as e:
        logging.error(f"Progress tracking error: {e}")

def humanbytes(size_in_bytes):
    """
    Convert bytes to human-readable format
    
    :param size_in_bytes: Size in bytes
    :return: Formatted string of file size
    """
    if size_in_bytes == 0:
        return "0 B"
    
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_in_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_in_bytes / p, 2)
    
    return f"{s} {size_name[i]}"

async def download_youtube(
    url, 
    progress_msg, 
    start_time, 
    filename
):
    """
    Download YouTube video or audio with enhanced error handling
    
    :param url: YouTube URL
    :param progress_msg: Message to update progress
    :param start_time: Start time of download
    :param filename: Desired filename
    :return: Path to downloaded file or None
    """
    try:
        # Ensure downloads directory exists
        os.makedirs('downloads', exist_ok=True)
        
        # Prepare yt-dlp options
        ydl_opts = {
            'outtmpl': os.path.join('downloads', filename),
            'nooverwrites': True,
            'no_color': True,
            'progress_hooks': [],
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': False,
            'noplaylist': True,
        }
        
        # Track download progress
        def progress_hook(d):
            try:
                if d['status'] == 'downloading':
                    downloaded_bytes = d.get('downloaded_bytes', 0)
                    total_bytes = d.get('total_bytes_estimate', 0)
                    
                    # Ensure progress message is still valid
                    if total_bytes > 0:
                        try:
                            # Create progress status message
                            status_message = (
                                f"🎥 **YouTube Download**\n"
                                f"📥 Downloading: `{filename}`\n"
                                f"⬇️ Progress: {downloaded_bytes/total_bytes*100:.1f}%"
                            )
                            
                            # Attempt to update message, with fallback methods
                            if hasattr(progress_msg, 'edit_text'):
                                asyncio.create_task(
                                    safe_edit_message(progress_msg, status_message)
                                )
                        except Exception as edit_error:
                            logging.warning(f"Progress update error: {edit_error}")
            except Exception as hook_error:
                logging.error(f"Progress hook error: {hook_error}")
        
        # Add progress hook
        ydl_opts['progress_hooks'].append(progress_hook)
        
        # Determine download type based on URL
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract video info
                info_dict = ydl.extract_info(url, download=True)
                
                if not info_dict:
                    # Update error message
                    if hasattr(progress_msg, 'edit_text'):
                        await progress_msg.edit_text("❌ **YouTube Download Failed**: Unable to extract video info")
                    else:
                        await progress_msg.reply_text("❌ **YouTube Download Failed**: Unable to extract video info")
                    return None
                
                # Get the actual downloaded file path
                downloaded_files = ydl.get_download_path(info_dict)
                
                # Validate downloaded files
                if not downloaded_files:
                    # Update error message
                    if hasattr(progress_msg, 'edit_text'):
                        await progress_msg.edit_text("❌ **YouTube Download Failed**: No files downloaded")
                    else:
                        await progress_msg.reply_text("❌ **YouTube Download Failed**: No files downloaded")
                    return None
                
                # Return the first downloaded file
                downloaded_file = downloaded_files[0]
                
                # Final success message
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text(f"✅ **Download Complete**: `{os.path.basename(downloaded_file)}`")
                else:
                    await progress_msg.reply_text(f"✅ **Download Complete**: `{os.path.basename(downloaded_file)}`")
                
                return downloaded_file
        
        except Exception as yt_error:
            logging.error(f"YouTube Download Error: {yt_error}")
            
            # Detailed error handling
            error_message = str(yt_error)
            if "Private video" in error_message:
                error_text = "❌ **Download Failed**: Private video"
            elif "Unavailable video" in error_message:
                error_text = "❌ **Download Failed**: Video unavailable"
            elif "Geoblocked" in error_message:
                error_text = "❌ **Download Failed**: Video geoblocked"
            else:
                error_text = f"❌ **YouTube Download Failed**: {error_message}"
            
            # Update error message
            try:
                if hasattr(progress_msg, 'edit_text'):
                    await progress_msg.edit_text(error_text)
                else:
                    await progress_msg.reply_text(error_text)
            except Exception as msg_error:
                logging.error(f"Error sending message: {msg_error}")
            
            return None
    
    except Exception as general_error:
        logging.error(f"General YouTube Download Error: {general_error}")
        
        # Final fallback error message
        try:
            if hasattr(progress_msg, 'edit_text'):
                await progress_msg.edit_text(f"❌ **Download Failed**: {str(general_error)}")
            else:
                await progress_msg.reply_text(f"❌ **Download Failed**: {str(general_error)}")
        except:
            pass
        
        return None

async def safe_edit_message(message, text):
    """
    Safely edit a message with multiple fallback strategies
    
    :param message: Message to edit
    :param text: New text content
    :return: True if edit successful, False otherwise
    """
    try:
        # Primary method: edit_text
        await message.edit_text(text)
        return True
    except FloodWait as flood:
        # Handle Telegram flood wait
        logging.warning(f"Flood wait: {flood.x} seconds")
        await asyncio.sleep(flood.x)
        return await safe_edit_message(message, text)
    except Exception as e:
        # Log and attempt alternative methods
        logging.warning(f"Message edit failed: {e}")
        try:
            # Fallback: reply to original message
            await message.reply_text(text)
            return True
        except:
            # Final fallback: log error
            logging.error(f"Failed to update message: {e}")
            return False

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

# Dictionary to track recent bot messages
recent_bot_messages = {}

async def clean_previous_messages(client, chat_id, user_id, max_messages=3):
    """
    Clean up previous bot messages for a specific user
    
    :param client: Pyrogram client
    :param chat_id: Chat ID to clean messages from
    :param user_id: User ID whose messages to clean
    :param max_messages: Maximum number of messages to keep
    """
    try:
        # Get the list of recent bot messages for this user
        user_messages = recent_bot_messages.get(user_id, [])
        
        # Delete excess messages
        while len(user_messages) > max_messages:
            oldest_message = user_messages.pop(0)
            try:
                await client.delete_messages(chat_id, oldest_message)
            except Exception as delete_error:
                logging.warning(f"Could not delete message {oldest_message}: {delete_error}")
        
        # Update the user's message list
        recent_bot_messages[user_id] = user_messages
    except Exception as e:
        logging.error(f"Message cleanup error: {e}")

async def send_tracked_message(
    client, 
    chat_id, 
    text, 
    user_id=None, 
    reply_markup=None, 
    parse_mode=None
):
    """
    Send a message and track it for potential cleanup
    
    :param client: Pyrogram client
    :param chat_id: Chat to send message to
    :param text: Message text
    :param user_id: User ID to associate the message with
    :param reply_markup: Optional reply markup
    :param parse_mode: Optional parse mode
    :return: Sent message
    """
    try:
        # Send the message
        message = await client.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        
        # Track the message if user_id is provided
        if user_id:
            # Initialize user's message list if not exists
            if user_id not in recent_bot_messages:
                recent_bot_messages[user_id] = []
            
            # Add the new message ID
            recent_bot_messages[user_id].append(message.id)
            
            # Clean up previous messages
            await clean_previous_messages(client, chat_id, user_id)
        
        return message
    except Exception as e:
        logging.error(f"Tracked message send error: {e}")
        return None

@bot.on_message(filters.command(["start"]) & filters.private)
async def start_command(client, message: Message):
    """
    Handle /start command
    
    :param client: Pyrogram client
    :param message: Incoming message
    """
    try:
        # Delete the user's command message
        try:
            await client.delete_messages(
                chat_id=message.chat.id, 
                message_ids=[message.id]
            )
        except Exception as delete_error:
            logging.warning(f"Could not delete start command message: {delete_error}")
        
        # Get user info
        status, storage, features = await get_user_info(message.from_user.id)
        
        # Create keyboard
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                InlineKeyboardButton("❓ Help", callback_data="help")
            ],
            [
                InlineKeyboardButton("🤖 About", callback_data="about")
            ],
            [
                InlineKeyboardButton("💫 Support", url="https://t.me/your_support_group"),
                InlineKeyboardButton("🤝 Join Channel", url="https://t.me/your_channel")
            ],
            [
                InlineKeyboardButton("❌ Close", callback_data="close")
            ]
        ])
        
        # Send welcome message
        welcome_message = await send_tracked_message(
            client=client,
            chat_id=message.chat.id,
            text=START_TEXT.format(
                first_name=message.from_user.first_name,
                status=status,
                storage=storage,
                features=features
            ),
            user_id=message.from_user.id,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        
        return welcome_message
    
    except Exception as e:
        logging.error(f"Start command error: {str(e)}")
        try:
            await message.reply_text(f"❌ An error occurred: {str(e)}")
        except:
            pass

@bot.on_message(filters.command(["help"]) & filters.private)
async def help_command(client, message: Message):
    """
    Handle /help command
    
    :param client: Pyrogram client
    :param message: Incoming message
    """
    try:
        # Delete the user's command message
        try:
            await client.delete_messages(
                chat_id=message.chat.id, 
                message_ids=[message.id]
            )
        except Exception as delete_error:
            logging.warning(f"Could not delete help command message: {delete_error}")
        
        # Create keyboard
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Back to Start", callback_data="start")
            ]
        ])
        
        # Send help message
        help_message = await send_tracked_message(
            client=client,
            chat_id=message.chat.id,
            text=HELP_TEXT,
            user_id=message.from_user.id,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        
        return help_message
    
    except Exception as e:
        logging.error(f"Help command error: {str(e)}")
        try:
            await message.reply_text(f"❌ An error occurred: {str(e)}")
        except:
            pass

@bot.on_message(filters.command(["about"]) & filters.private)
async def about_command(client, message: Message):
    """
    Handle /about command
    
    :param client: Pyrogram client
    :param message: Incoming message
    """
    try:
        # Delete the user's command message
        try:
            await client.delete_messages(
                chat_id=message.chat.id, 
                message_ids=[message.id]
            )
        except Exception as delete_error:
            logging.warning(f"Could not delete about command message: {delete_error}")
        
        # Create keyboard
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🏠 Back to Start", callback_data="start")
            ]
        ])
        
        # Send about message
        about_message = await send_tracked_message(
            client=client,
            chat_id=message.chat.id,
            text=ABOUT_TEXT,
            user_id=message.from_user.id,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN
        )
        
        return about_message
    
    except Exception as e:
        logging.error(f"About command error: {str(e)}")
        try:
            await message.reply_text(f"❌ An error occurred: {str(e)}")
        except:
            pass

@bot.on_callback_query()
async def callback_handler(client, callback_query):
    """
    Handle all inline button callbacks with comprehensive error management
    
    :param client: Pyrogram client
    :param callback_query: Incoming callback query
    """
    try:
        # Log the callback data for debugging
        logging.info(f"Received callback data: {callback_query.data}")
        
        # Ensure callback query is valid
        if not callback_query or not callback_query.data:
            logging.warning("Invalid or empty callback query")
            return
        
        data = callback_query.data
        message = callback_query.message
        
        # Validate message
        if not message:
            logging.warning("No message associated with callback")
            await callback_query.answer("Invalid callback", show_alert=True)
            return
        
        chat_id = message.chat.id
        user_id = callback_query.from_user.id
        
        # Always answer the callback query to prevent hanging
        try:
            await callback_query.answer(
                "Processing your request...",
                show_alert=False
            )
        except Exception as answer_error:
            logging.error(f"Callback answer error: {answer_error}")
        
        # Comprehensive callback handling with extensive error protection
        try:
            if data == "start":
                # Start menu
                status, storage, features = await get_user_info(user_id)
                
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
                        InlineKeyboardButton("❓ Help", callback_data="help")
                    ],
                    [
                        InlineKeyboardButton("🤖 About", callback_data="about")
                    ],
                    [
                        InlineKeyboardButton("💫 Support", url="https://t.me/your_support_group"),
                        InlineKeyboardButton("🤝 Join Channel", url="https://t.me/your_channel")
                    ],
                    [
                        InlineKeyboardButton("❌ Close", callback_data="close")
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
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.MARKDOWN
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
                    disable_web_page_preview=True,
                    parse_mode=ParseMode.MARKDOWN
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
            
            elif data == "close":
                # Delete the message when close button is pressed
                try:
                    await message.delete()
                except Exception as e:
                    logging.error(f"Error deleting message: {str(e)}")
                    await callback_query.answer("Could not close the message.", show_alert=True)
            
            # Handling download and rename buttons
            elif data.startswith("default|"):
                file_id = data.split("|")[1]
                url = pending_downloads.get(file_id)
                
                if not url:
                    await callback_query.answer("❌ Link expired. Please send the URL again.", show_alert=True)
                    return
                
                # Delete the selection message
                try:
                    await message.delete()
                except Exception as delete_error:
                    logging.warning(f"Could not delete selection message: {delete_error}")
                
                # Perform quick download
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
            
            elif data.startswith("cancel|"):
                file_id = data.split("|")[1]
                
                # Remove from pending downloads
                pending_downloads.pop(file_id, None)
                
                # Delete the selection message
                try:
                    await message.delete()
                except Exception as delete_error:
                    logging.warning(f"Could not delete selection message: {delete_error}")
            
            else:
                # Unknown callback data
                await callback_query.answer("❌ Invalid button.", show_alert=True)
        
        except Exception as callback_error:
            logging.error(f"Callback Handler Error: {callback_error}")
            try:
                await message.edit_text(f"❌ An unexpected error occurred: {str(callback_error)}")
            except:
                await callback_query.answer(f"❌ An unexpected error occurred", show_alert=True)
    
    except Exception as global_error:
        logging.critical(f"Global Callback Handler Error: {global_error}")
        try:
            await callback_query.answer("❌ A critical error occurred", show_alert=True)
        except:
            pass

@bot.on_message(filters.private & filters.text)
async def handle_message(client, message):
    """
    Handle incoming messages with advanced URL processing
    """
    try:
        # Get user details
        user_id = message.from_user.id
        chat_id = message.chat.id
        text = message.text.strip()
        
        # Clean up previous bot messages for this user
        await clean_previous_messages(client, chat_id, user_id)
        
        # Check for rename operation
        if chat_id in pending_renames:
            if text.lower() == "/cancel":
                await send_tracked_message(
                    client, 
                    chat_id, 
                    "❌ **Rename Process Cancelled**",
                    user_id=user_id
                )
                pending_renames.pop(chat_id, None)
                return
            
            rename_info = pending_renames.pop(chat_id)
            if rename_info.get("type") == "youtube":
                await download_youtube(client, message, rename_info["url"], text)
            else:
                await handle_download_or_upload(
                    client, 
                    message, 
                    rename_info["url"], 
                    custom_filename=text
                )
            return
        
        # Ignore command messages
        if text.startswith('/'):
            return
        
        # YouTube download
        if re.match(YOUTUBE_REGEX, text):
            await download_youtube(client, message, text)
            return
        
        # Direct download URL
        if re.match(URL_REGEX, text):
            # Get file details
            try:
                file_size = await get_file_size(text)
                original_filename = await get_filename(text) or "File"
                
                # Check file size limit
                if file_size and file_size > 2 * 1024 * 1024 * 1024:  # 2GB limit
                    await send_tracked_message(
                        client, 
                        chat_id, 
                        f"❌ **File size ({humanbytes(file_size)}) is too large!**\n\n"
                        "Maximum allowed size is 2GB",
                        user_id=user_id
                    )
                    return
                
                # Generate unique file ID
                file_id = str(uuid.uuid4())
                pending_downloads[file_id] = text
                
                # Create download options keyboard
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⚡️ Quick Download", 
                            callback_data=f"default|{file_id}"
                        ),
                        InlineKeyboardButton(
                            "✏️ Custom Name", 
                            callback_data=f"rename|{file_id}"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "❌ Cancel", 
                            callback_data=f"cancel|{file_id}"
                        )
                    ]
                ])
                
                # Send file info message with options
                await send_tracked_message(
                    client, 
                    chat_id, 
                    f"**🔗 URL Detected!**\n\n"
                    f"📦 **File Size:** {humanbytes(file_size) if file_size else 'Unknown'}\n"
                    f"📄 **Original Name:** `{original_filename}`\n"
                    f"🎯 **Choose an option:**",
                    user_id=user_id,
                    reply_markup=keyboard
                )
            
            except Exception as url_error:
                logging.error(f"URL processing error: {url_error}")
                await send_tracked_message(
                    client, 
                    chat_id, 
                    f"❌ **Error processing URL**: {str(url_error)}",
                    user_id=user_id
                )
            return
        
        # Invalid input
        await send_tracked_message(
            client, 
            chat_id, 
            "❌ **Please send me a valid direct download link or YouTube URL!**",
            user_id=user_id
        )
    
    except Exception as e:
        logging.error(f"Message handler error: {e}")
        try:
            await message.reply_text(f"❌ An error occurred: {str(e)}")
        except:
            pass

async def get_user_info(user_id):
    """
    Placeholder function to get user information
    
    :param user_id: Telegram user ID
    :return: Tuple of (status, storage, features)
    """
    # Default values if no specific user info is available
    return "Free User", "0 MB / 2 GB", "Basic Features"

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
