import os

# Pyrogram setup
API_ID = int(os.environ.get("API_ID", "22706527"))  # Replace with actual API ID
API_HASH = os.environ.get("API_HASH", "c8dfc568ef750d4ac69723924766a7f7")  # Replace with actual API HASH
BOT_TOKEN = os.environ.get("BOT_TOKEN", "7643545087:AAHMwI-sn16xD1bQuUBCP-C-kQNAVSvv-Ek")  # Replace with actual BOT_TOKEN
SESSION_STRING = os.environ.get("SESSION_STRING", "BQFaeV8AjMhWpjCt50an2xxDSWyDQkw0kBXvyZiygxlF0aEgU8eULldJNS2ZeO1UyCcRohRotHaZWHDTl6Wo2Gl2eu8hn5y6AK8sYLaUuGg0GWYZ0Aahz1jWLbiLftN0AKQti8o6oY1cIkCLbxnRkXJjcg8zCh57WlfGDLmulTfIEGvjX6l3gJCEnkL5vZNSOk6-wE-v-tZC3KtHAWU2Wb3XZgbBQ4Zj_w8b3waRUEk1DE61N0hD5Q4x0Sb_7hZK-LYD7GBCM7xMGsF_3jJf93lvrYdeHuLJ9jw6fiUwn6sbaCS1etW514PNJd8i1wstGJW1U2YKSMeaUkuYr_WXa6BHAEbn8QAAAAHHlz3_AQ")  # Replace with actual SESSION STRING

OWNER_ID = int(os.environ.get("OWNER_ID", "5825793375"))  # Replace with actual owner ID

# File size limit (4GB)
MAX_FILE_SIZE = 4 * 1024 * 1024 * 1024  # 4GB in bytes
DOWNLOAD_LOCATION = "./DOWNLOADS"  # File / video download location

# Chunk size that should be used with requests
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", 128))

# Proxy for accessing youtube-dl in GeoRestricted Areas
HTTP_PROXY = os.environ.get("HTTP_PROXY", "TP73313458:vAbYCAvl@208.195.167.246:65095")

# Set timeout for subprocess
PROCESS_MAX_TIMEOUT = 3700

# Bot request dictionary
ADL_BOT_RQ = {}
AUTH_USERS = [OWNER_ID]
