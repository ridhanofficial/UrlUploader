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
import traceback

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode

import yt_dlp
import aiohttp
import aiofiles

# Import config variables directly
from config import (
    API_ID, API_HASH, BOT_TOKEN, SESSION_STRING, 
    OWNER_ID, MAX_FILE_SIZE, DOWNLOAD_LOCATION
)

# Utility functions
from plugins.utils import get_filename, get_file_size, file_size_format
from helpers.utils import async_download_file

# Define text constants
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
• `/broadcast` - Broadcast a message (Owner only)

**Usage:**

• Send a direct download link or YouTube URL to upload a file
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
                
                # Create rows of 2
