import re
import os
import logging
import aiohttp
import time

PROGRESS_BAR_TEMPLATE = """
Percentage: {percentage} | {current}
Total Completed: {total}%
Current Speed: {speed}/s
Estimated Time: {est_time}
"""

def progressArgs(action: str, progress_message, start_time):
    return (
        action,
        progress_message,
        start_time,
        PROGRESS_BAR_TEMPLATE,
        '▓',
        '░'
    )

async def async_download_file(url, filename, progress=None, progress_args=()):
    download_directory = "Download"
    if not os.path.exists(download_directory):
        os.makedirs(download_directory)
    
    file_path = os.path.join(download_directory, filename)

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status != 200:
                raise Exception("Download failed")
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded_size = 0

            with open(file_path, "wb") as file:
                async for chunk in response.content.iter_chunked(1024):
                    file.write(chunk)
                    downloaded_size += len(chunk)
                    if progress:
                        await progress(downloaded_size, total_size, *progress_args)
    
    return file_path

def file_size_format(num, suffix='B'):
    for unit in ['', 'Ki', 'Mi', 'Gi', 'Ti', 'Pi', 'Ei', 'Zi']:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

async def get_file_size(url):
    async with aiohttp.ClientSession() as session:
        async with session.head(url, allow_redirects=True) as response:
            size = response.headers.get('content-length')
            if size:
                return int(size)
            else:
                return 0

async def get_filename(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True) as response:
                content_disposition = response.headers.get('Content-Disposition')
                if content_disposition:
                    filename_match = re.findall('filename="(.+)"', content_disposition)
                    if filename_match:
                        return filename_match[0]

                return url.split('/')[-1].split('?')[0]
    except Exception as e:
        logging.error(f"Error fetching filename from headers: {str(e)}")
        return url.split('/')[-1].split('?')[0]

async def progress(current, total, message, start, action):
    now = time.time()
    diff = now - start
    
    if diff < 1:
        return
    
    speed = current / diff
    percentage = (current * 100) / total
    
    # Premium progress bar
    bar_length = 10
    current_bar = int(percentage / (100 / bar_length))
    bar = "▰" * current_bar + "▱" * (bar_length - current_bar)
    
    # Calculate time remaining
    time_to_completion = round((total - current) / speed)
    estimated_total_time = TimeFormatter(time_to_completion)
    
    # Format speed and sizes
    speed_text = f"{humanbytes(speed)}/s"
    current_text = humanbytes(current)
    total_text = humanbytes(total)
    
    # Premium-style progress message
    progress_text = f"""
**{action} in Progress** 🚀

{bar} `{percentage:.1f}%`

**⚡️ Speed:** `{speed_text}`
**📊 Progress:** `{current_text} / {total_text}`
**⏱ Time Left:** `{estimated_total_time}`
"""
    
    try:
        await message.edit_text(
            text=progress_text,
            parse_mode='markdown'
        )
    except Exception:
        pass

def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    
    tmp = (
        (f"{str(days)}d, " if days else "") +
        (f"{str(hours)}h, " if hours else "") +
        (f"{str(minutes)}m, " if minutes else "") +
        (f"{str(seconds)}s" if seconds else "")
    )
    return tmp or "0s"

def humanbytes(size: int) -> str:
    if not size:
        return "0B"
    
    power = 2 ** 10  # 1024
    raised_to_pow = 0
    dict_power_n = {
        0: "B", 1: "KB", 2: "MB", 3: "GB", 4: "TB"
    }
    
    while size > power:
        size /= power
        raised_to_pow += 1
    
    return f"{str(round(size, 2))} {dict_power_n[raised_to_pow]}"
