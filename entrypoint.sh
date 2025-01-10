#!/bin/bash

# Check if required environment variables are set
if [ -z "$BOT_TOKEN" ] || [ -z "$API_ID" ] || [ -z "$API_HASH" ]; then
    echo "Error: Missing required environment variables"
    echo "Please set BOT_TOKEN, API_ID, and API_HASH"
    exit 1
fi

# Run the bot
exec python -m uploder
