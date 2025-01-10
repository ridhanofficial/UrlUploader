import re
import os
import logging
import aiohttp

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
