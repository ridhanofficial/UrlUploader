import os

# Pyrogram setup
API_ID = int(os.environ.get("API_ID", "12345678"))  # Replace with actual API ID
API_HASH = os.environ.get("API_HASH", "XXXXXXXXXXXXXXXXX")  # Replace with actual API HASH
BOT_TOKEN = os.environ.get("BOT_TOKEN", "XXXXXXXXXXXX")  # Replace with actual BOT_TOKEN
SESSION_STRING = os.environ.get("SESSION_STRING", "XXXXXXXXXXXXXXXXXXXXXX")  # Replace with actual SESSION STRING

OWNER_ID = int(os.environ.get("OWNER_ID", "12345678"))  # Replace with actual owner ID

# File size limit (4GB)
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4GB in bytes
DOWNLOAD_LOCATION = "./DOWNLOADS"  # File / video download location

# Chunk size that should be used with requests
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 128))

# Proxy for accessing youtube-dl in GeoRestricted Areas
HTTP_PROXY = os.environ.get("HTTP_PROXY", "")

# Set timeout for subprocess
PROCESS_MAX_TIMEOUT = 3700

# Bot request dictionary
ADL_BOT_RQ = {}
AUTH_USERS = [OWNER_ID]
