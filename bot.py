# ... (rest of the imports and setup remain the same) ...

# --- Handlers for Admin Commands ---
# ... (all admin commands remain the same: cmd_send, cmd_list, etc.) ...

# --- New Handler for Non-Text Messages ---

async def handle_non_text_messages(message: types.Message):
    """
    Handles non-text updates (photos, stickers, service messages) to prevent 'is not handled' warnings.
    If the chat is locked, these messages are deleted.
    """
    if not message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return

    chat_id = message.chat.id
    _, _, _, _, _, chat_is_locked = get_session_data(chat_id)
    
    # If the chat is locked, delete the non-text message
    if chat_is_locked:
        try:
            await message.delete()
        except Exception as e:
            logger.warning(f"Could not delete non-text message in locked chat {chat_id}: {e}")
    
    # Otherwise, simply let the bot ignore it silently without logging a warning
    # The 'is not handled' is now logged as INFO by aiogram, but this explicitly handles the Update.


# --- Handler for User Messages (Link Sharing and AD/Done) ---

async def handle_user_messages(message: types.Message):
    """Handles link sharing and 'AD' messages from regular users."""
    
    if not message.from_user or not message.text:
        # NOTE: Non-text messages will be caught by handle_non_text_messages below
        return

    chat_id = message.chat.id
    user_id = message.from_user.id
    user_text = message.text.strip()
    
    participants_map, x_handles_map, completed_users_map, display_names_map, session_is_active, chat_is_locked = get_session_data(chat_id)

    # 1. Handle "AD/Done" messages
    ad_keywords = {"ad", "done", "all done", "completed"}
    if user_text.lower() in ad_keywords:
        
        if not session_is_active:
            return

        recorded_links = participants_map.get(user_id) 
        
        if not recorded_links:
            await message.reply("Your link hasn't been recorded yet. Please send your X link first.")
            return

        completed_users_map[user_id] = True
        
        user_mention = display_names_map.get(user_id, get_user_mention(message.from_user))
        last_recorded_link = recorded_links[-1] 
        
        response = (
            f"ENGAGEMENT RECORDED 👍 for {user_mention}\n"
            f"Their X link:\n{last_recorded_link}" 
        )
        await message.reply(response, parse_mode="HTML") 
        logger.info(f"AD/Done recorded for {user_id} in chat {chat_id}.")
        return

    # 2. Handle Link Sharing
    if is_x_link(user_text):
        
        if chat_is_locked:
            try:
                await message.delete()
            except Exception:
                pass
            return
            
        if not session_is_active:
             await message.reply("The bot session is currently idle. Please wait for an admin to start a new session with /send.")
             return
            
        user_links = participants_map.setdefault(user_id, [])
        if len(user_links) >= MAX_LINKS_PER_USER:
            try:
                await message.delete()
            except Exception:
                pass
            return
            
        x_username = extract_x_username(user_text)
        
        if not x_username:
            await message.reply("Could not extract an X username from the link. Please ensure it's a valid `x.com/<username>/status/...` link.")
            return
            
        user_links.append(user_text) 
        if user_id not in x_handles_map:
            x_handles_map[user_id] = x_username
        
        completed_users_map[user_id] = False 
        display_names_map[user_id] = get_user_mention(message.from_user) 
        
        user_mention = get_user_mention(message.from_user)
        link_count = len(user_links)
        await message.reply(f"✅ Link {link_count}/{MAX_LINKS_PER_USER} from {user_mention} recorded ({x_username})", parse_mode="HTML")

        logger.info(f"Link {link_count} received from {user_id} in chat {chat_id}. X Handle: {x_username}.")
        
    else:
        # Regular chat message: delete if locked
        if chat_is_locked:
            try:
                await message.delete()
            except Exception:
                pass
                
# ... (rest of the error handling remains the same) ...

# --- Main Bot Setup ---

def setup_bot_handlers(dp: Dispatcher, admin_filter: GroupAdminFilter):
    """Registers all command and message handlers."""
    
    # Admin Commands
    dp.message.register(cmd_send, Command("send"), admin_filter)
    dp.message.register(cmd_list, Command("list"), admin_filter)
    dp.message.register(cmd_xlist, Command("xlist"), admin_filter)
    dp.message.register(cmd_adlist, Command("adlist"), admin_filter)
    dp.message.register(cmd_notad, Command("notad"), admin_filter)
    dp.message.register(cmd_refresh, Command("refresh"), admin_filter)
    dp.message.register(cmd_lock, Command("lock"), admin_filter) 
    dp.message.register(cmd_unlock, Command("unlock"), admin_filter) 
    dp.message.register(cmd_stop, Command("stop"), admin_filter)
    dp.message.register(cmd_rs, Command("rs"), admin_filter)
    dp.message.register(cmd_detect, Command("detect"), admin_filter)
    
    # User Message Handler (Text)
    dp.message.register(
        handle_user_messages, 
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), 
        F.text
    )
    
    # NEW: Catch-all handler for non-text messages (e.g., photos, stickers)
    dp.message.register(
        handle_non_text_messages,
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
        ~F.text # Matches messages that do NOT have the text field set
    )
    
    dp.error.register(on_error)
    logger.info("Bot handlers registered successfully.")

# ... (rest of the main and webserver functions remain the same) ...
