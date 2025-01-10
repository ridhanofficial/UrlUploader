import re
import aiohttp

async def get_file_extension_from_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.head(url, allow_redirects=True) as response:
            content_type = response.headers.get('Content-Type')
            if content_type:
                return content_type.split('/')[-1]
    return "jpg"

def get_resolution(info_dict):
    width = info_dict.get("width", 0)
    height = info_dict.get("height", 0)
    return width, height
