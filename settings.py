import asyncio
import logging
from pyrogram import types, errors, enums
from plugins.config import Config
from plugins.database.database import db

logger = logging.getLogger(__name__)

async def open_settings(m: "types.Message"):
    """
    Open user settings with an inline keyboard for configuration
    
    Args:
        m (types.Message): The message to edit with settings
    """
    usr_id = m.chat.id
    user_data = await db.get_user_data(usr_id)
    
    if not user_data:
        await m.edit("❌ Failed to fetch your data from database!")
        return
    
    # Default settings if not found
    upload_as_doc = user_data.get("upload_as_doc", False)
    thumbnail = user_data.get("thumbnail", None)
    
    buttons_markup = [
        [types.InlineKeyboardButton(
            f"ᴜᴘʟᴏᴀᴅ ᴀs {'🎥 ᴠɪᴅᴇᴏ' if upload_as_doc else '🗃️ Fɪʟᴇ'}",
            callback_data="triggerUploadMode"
        )],
        [types.InlineKeyboardButton(
            f"{'ᴄʜᴀɴɢᴇ' if thumbnail else '🌃 sᴇᴛ'} ᴛʜᴜᴍʙɴᴀɪʟ",
            callback_data="setThumbnail"
        )]
    ]
    
    if thumbnail:
        buttons_markup.append([
            types.InlineKeyboardButton(
                "🌆 sʜᴏᴡ ᴛʜᴜᴍʙɴᴀɪʟ", 
                callback_data="showThumbnail"
            )
        ])
    
    buttons_markup.append([
        types.InlineKeyboardButton(
            "♨️ ᴄʟᴏsᴇ", 
            callback_data="close"
        )
    ])

    try:
        await m.edit(
            text="**ʜᴇʀᴇ ʏᴏᴜ ᴄᴀɴ sᴇᴛᴜᴘ ʏᴏᴜʀ sᴇᴛᴛɪɴɢs**",
            reply_markup=types.InlineKeyboardMarkup(buttons_markup),
            disable_web_page_preview=True,
            parse_mode=enums.ParseMode.MARKDOWN
        )
    except errors.MessageNotModified:
        pass
    except errors.FloodWait as e:
        logger.warning(f"Flood wait: sleeping for {e.x} seconds")
        await asyncio.sleep(e.x)
        try:
            await open_settings(m)
        except Exception as retry_err:
            logger.error(f"Failed to retry settings: {retry_err}")
    except Exception as err:
        logger.error(f"Error in open_settings: {err}")
