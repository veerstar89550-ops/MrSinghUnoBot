"""
UNO Telegram Bot
────────────────
Commands (in group):
  /newgame  - Open a lobby
  /scores   - Show leaderboard
  /endgame  - End current game (creator only)

Commands (in DM):
  /start    - Activate DM so bot can send you cards
"""

import os
import logging
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from uno_game import (
    UnoGame,
    card_display,
    can_play,
    COLORS,
    COLOR_EMOJI,
)

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
TOKEN = os.environ['BOT_TOKEN']
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', '').rstrip('/')
PORT = int(os.environ.get('PORT', 8443))

# ── State ──────────────────────────────────────────────────────────────────
games: dict[int, UnoGame] = {}       # chat_id  → UnoGame
player_chat: dict[int, int] = {}     # user_id  → group chat_id


# ══════════════════════════════════════════════════════════════════════════
# ─── Helpers ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

MEDALS = ['🥇', '🥈', '🥉']


def _medal(i: int) -> str:
    return MEDALS[i] if i < 3 else f'{i + 1}.'


def status_text(game: UnoGame) -> str:
    cur_uid, cur_name = game.current_player()
    color_e = COLOR_EMOJI.get(game.current_color, '🌈')
    top = card_display(game.top_card) if game.top_card else '—'
    lines = [
        f"🎴 Top card : {top}",
        f"🎨 Color    : {color_e} {game.current_color.capitalize()}",
        f"👤 Turn     : *{cur_name}*",
        '',
        '*Players:*',
    ]
    for uid, name in game.players:
        count = len(game.hands.get(uid, []))
        flags = ''
        if count == 1:
            flags += ' 🔔UNO' if uid in game.uno_safe else ' ⚠️UNO?'
        lines.append(f'  • {name} — {count} card(s){flags}')
    return '\n'.join(lines)


def group_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('🃏 My Cards (DM)', callback_data='open_hand'),
            InlineKeyboardButton('➕ Draw Card', callback_data='draw'),
        ],
        [
            InlineKeyboardButton('🔔 UNO!', callback_data='uno'),
            InlineKeyboardButton('😈 Catch UNO!', callback_data='catch_uno'),
        ],
    ])


def lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('✋ Join', callback_data='join'),
        InlineKeyboardButton('▶️ Start', callback_data='start'),
    ]])


def color_keyboard(card: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f'{COLOR_EMOJI[c]} {c.capitalize()}',
            callback_data=f'color|{card}|{c}',
        )
        for c in COLORS
    ]])


def hand_keyboard(game: UnoGame, uid: int, group_chat_id: int) -> InlineKeyboardMarkup:
    hand = game.hands.get(uid, [])
    top = game.top_card
    buttons = []
    row = []
    for card in hand:
        playable = can_play(card, game.current_color, top)
        label = card_display(card) + ('' if playable else ' ✗')
        cb = f'play|{group_chat_id}|{card}' if playable else 'noop'
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        '➕ Draw a Card', callback_data=f'drawdm|{group_chat_id}'
    )])
    return InlineKeyboardMarkup(buttons)


async def _send_hand(ctx: ContextTypes.DEFAULT_TYPE,
                     game: UnoGame, uid: int, group_chat_id: int,
                     edit_msg_id: int | None = None) -> bool:
    """DM the player their hand. Returns False if bot can't reach them."""
    hand = game.hands.get(uid, [])
    cur_uid, cur_name = game.current_player()
    is_turn = uid == cur_uid
    top = card_display(game.top_card) if game.top_card else '—'
    color_e = COLOR_EMOJI.get(game.current_color, '🌈')

    text = (
        f"🃏 *Your hand* ({len(hand)} cards)\n"
        f"Top: {top}  |  Color: {color_e}\n\n"
        + ('✅ *Your turn — play a card!*' if is_turn else f'⏳ Waiting for *{cur_name}*…')
    )
    kb = hand_keyboard(game, uid, group_chat_id)

    try:
        if edit_msg_id:
            await ctx.bot.edit_message_text(
                text, chat_id=uid, message_id=edit_msg_id,
                parse_mode='Markdown', reply_markup=kb,
            )
        else:
            await ctx.bot.send_message(
                uid, text, parse_mode='Markdown', reply_markup=kb,
            )
        return True
    except Exception as exc:
        logger.warning('Cannot DM %s: %s', uid, exc)
        return False


async def _finish_game(ctx: ContextTypes.DEFAULT_TYPE,
                       game: UnoGame, group_chat_id: int,
                       winner_name: str, points: int):
    lb = game.leaderboard()
    lines = [
        f'🎉 *{winner_name} wins — {points} points earned!*\n',
        '🏆 *Final Leaderboard:*',
    ]
    for i, row in enumerate(lb):
        lines.append(
            f'{_medal(i)} {row["name"]} — {row["score"]} pts  '
            f'({row["wins"]} win{"s" if row["wins"] != 1 else ""})'
        )
    lines.append('\n🎮 Use /newgame to play again!')

    for uid, _ in game.players:
        player_chat.pop(uid, None)
    games.pop(group_chat_id, None)

    await ctx.bot.send_message(
        group_chat_id, '\n'.join(lines), parse_mode='Markdown',
    )


# ══════════════════════════════════════════════════════════════════════════
# ─── Commands ─────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """DM /start → confirm bot can message the user."""
    user = update.effective_user
    if update.effective_chat.type != 'private':
        return
    await update.message.reply_text(
        f'👋 Hi *{user.first_name}*!\n\n'
        f'I can now send your UNO cards here in private. '
        f'Go back to the group and join a game!',
        parse_mode='Markdown',
    )


async def cmd_newgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type == 'private':
        await update.message.reply_text('⚠️ Use /newgame in a group chat!')
        return
    if chat.id in games and games[chat.id].state == 'playing':
        await update.message.reply_text(
            '⚠️ A game is already running! Ask the creator to /endgame first.'
        )
        return

    game = UnoGame(chat.id, user.id, user.first_name)
    games[chat.id] = game
    player_chat[user.id] = chat.id

    await update.message.reply_text(
        f'🎴 *UNO Lobby*\n\n'
        f'Players (1/10):\n• {user.first_name}\n\n'
        f'⚠️ Before joining, open @{ctx.bot.username} in DM and send /start\n'
        f'Then click *Join* below!',
        parse_mode='Markdown',
        reply_markup=lobby_keyboard(),
    )


async def cmd_scores(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    game = games.get(update.effective_chat.id)
    if not game:
        await update.message.reply_text('No game in this chat yet. Use /newgame!')
        return
    lb = game.leaderboard()
    lines = ['🏆 *Leaderboard*\n']
    for i, row in enumerate(lb):
        lines.append(
            f'{_medal(i)} *{row["name"]}* — {row["score"]} pts  '
            f'({row["wins"]} wins, {row["cards"]} cards left)'
        )
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def cmd_endgame(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    game = games.get(chat.id)
    if not game:
        await update.message.reply_text('No game running!')
        return
    if user.id != game.creator_id:
        await update.message.reply_text('⚠️ Only the game creator can end the game.')
        return

    lb = game.leaderboard()
    lines = ['🛑 *Game ended by creator.*\n\n🏆 *Final Scores:*']
    for i, row in enumerate(lb):
        lines.append(f'{_medal(i)} {row["name"]} — {row["score"]} pts')

    for uid, _ in game.players:
        player_chat.pop(uid, None)
    games.pop(chat.id, None)

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


# ══════════════════════════════════════════════════════════════════════════
# ─── Callback Router ──────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data
    chat = query.message.chat

    await query.answer()

    # ── JOIN ──────────────────────────────────────────────────────────────
    if data == 'join':
        game = games.get(chat.id)
        if not game or game.state != 'waiting':
            await query.answer('No open lobby here!', show_alert=True)
            return
        res = game.join(user.id, user.first_name)
        if res == 'already':
            await query.answer("You're already in the lobby!", show_alert=True)
            return
        if res == 'full':
            await query.answer('The lobby is full (10/10)!', show_alert=True)
            return
        player_chat[user.id] = chat.id
        player_list = '\n'.join(f'• {n}' for _, n in game.players)
        try:
            await query.edit_message_text(
                f'🎴 *UNO Lobby*\n\nPlayers ({len(game.players)}/10):\n{player_list}\n\n'
                f'⚠️ Make sure you\'ve /start-ed @{ctx.bot.username} in DM!',
                parse_mode='Markdown',
                reply_markup=lobby_keyboard(),
            )
        except Exception:
            pass

    # ── START ─────────────────────────────────────────────────────────────
    elif data == 'start':
        game = games.get(chat.id)
        if not game:
            await query.answer('No game found!', show_alert=True)
            return
        if user.id != game.creator_id:
            await query.answer('Only the creator can start the game!', show_alert=True)
            return
        if not game.start():
            await query.answer('Need at least 2 players!', show_alert=True)
            return

        failed = []
        for uid, name in game.players:
            ok = await _send_hand(ctx, game, uid, chat.id)
            if not ok:
                failed.append(name)

        status = status_text(game)
        warn = ''
        if failed:
            warn = (
                f'\n\n⚠️ Could not DM: *{", ".join(failed)}*\n'
                f'They must send /start to @{ctx.bot.username} in DM!'
            )
        try:
            await query.edit_message_text(
                f'🎮 *Game Started!*\n\n{status}{warn}',
                parse_mode='Markdown',
                reply_markup=group_keyboard(),
            )
        except Exception:
            pass

    # ── OPEN HAND (group button) ───────────────────────────────────────────
    elif data == 'open_hand':
        game = games.get(chat.id)
        if not game or game.state != 'playing':
            await query.answer('No active game!', show_alert=True)
            return
        if user.id not in {u for u, _ in game.players}:
            await query.answer("You're not in this game!", show_alert=True)
            return
        ok = await _send_hand(ctx, game, user.id, chat.id)
        if ok:
            await query.answer('Cards sent to your DM ✉️')
        else:
            await query.answer(
                f'Please /start @{ctx.bot.username} in DM first!',
                show_alert=True,
            )

    # ── DRAW (group button) ────────────────────────────────────────────────
    elif data == 'draw':
        game = games.get(chat.id)
        if not game or game.state != 'playing':
            return
        cur_uid, cur_name = game.current_player()
        if user.id != cur_uid:
            await query.answer("It's not your turn!", show_alert=True)
            return
        drawn = game.draw(user.id, 1)
        card = drawn[0] if drawn else None
        if card and can_play(card, game.current_color, game.top_card):
            await query.answer(f'Drew {card_display(card)} — you can play it!', show_alert=True)
            await _send_hand(ctx, game, user.id, chat.id)
        else:
            game._advance()
            msg = f'Drew {card_display(card)}' if card else 'Deck empty — passed'
            await query.answer(msg, show_alert=True)
            next_uid, next_name = game.current_player()
            await _send_hand(ctx, game, next_uid, chat.id)
            try:
                await query.edit_message_text(
                    f'➕ *{user.first_name}* drew a card.\n\n{status_text(game)}',
                    parse_mode='Markdown',
                    reply_markup=group_keyboard(),
                )
            except Exception:
                pass

    # ── DRAW (DM button) ──────────────────────────────────────────────────
    elif data.startswith('drawdm|'):
        group_chat_id = int(data.split('|')[1])
        game = games.get(group_chat_id)
        if not game or game.state != 'playing':
            await query.answer('No active game!', show_alert=True)
            return
        cur_uid, cur_name = game.current_player()
        if user.id != cur_uid:
            await query.answer("It's not your turn!", show_alert=True)
            return
        drawn = game.draw(user.id, 1)
        card = drawn[0] if drawn else None
        if card and can_play(card, game.current_color, game.top_card):
            await query.answer(f'Drew {card_display(card)} — you can play it!', show_alert=True)
            # Refresh hand in DM
            try:
                await query.edit_message_text(
                    f'Drew *{card_display(card)}* — you can play it!\nUpdating hand…',
                    parse_mode='Markdown',
                )
            except Exception:
                pass
            await _send_hand(ctx, game, user.id, group_chat_id)
        else:
            game._advance()
            await query.answer(
                f'Drew {card_display(card) if card else "nothing"} — turn passed.',
                show_alert=True,
            )
            try:
                await query.edit_message_text(
                    f'➕ Drew a card. Turn passed. Waiting for your next turn…'
                )
            except Exception:
                pass
            next_uid, next_name = game.current_player()
            await _send_hand(ctx, game, next_uid, group_chat_id)
            try:
                await ctx.bot.send_message(
                    group_chat_id,
                    f'➕ *{user.first_name}* drew a card.\n\n{status_text(game)}',
                    parse_mode='Markdown',
                    reply_markup=group_keyboard(),
                )
            except Exception:
                pass

    # ── UNO CALL ─────────────────────────────────────────────────────────
    elif data == 'uno':
        game = games.get(chat.id)
        if not game or game.state != 'playing':
            return
        if user.id not in {u for u, _ in game.players}:
            return
        count = len(game.hands.get(user.id, []))
        if count == 1:
            game.uno_safe.add(user.id)
            await query.answer('🔔 UNO! You are safe!', show_alert=True)
            await ctx.bot.send_message(
                chat.id, f'🔔 *{user.first_name}* called UNO!', parse_mode='Markdown',
            )
        elif count == 0:
            await query.answer('You already won!', show_alert=True)
        else:
            await query.answer(f'You have {count} cards — can\'t call UNO yet!', show_alert=True)

    # ── CATCH UNO ────────────────────────────────────────────────────────
    elif data == 'catch_uno':
        game = games.get(chat.id)
        if not game or game.state != 'playing':
            return
        caught, target_name = game.catch_uno(user.id)
        if caught:
            await query.answer(f'😈 Caught {target_name}! They draw 2!', show_alert=True)
            await ctx.bot.send_message(
                chat.id,
                f'😈 *{user.first_name}* caught *{target_name}* not calling UNO!\n'
                f'*{target_name}* draws 2 cards as penalty!',
                parse_mode='Markdown',
            )
        else:
            await query.answer(
                "Nobody to catch — everyone called UNO or has >1 card.", show_alert=True,
            )

    # ── PLAY CARD (DM button) ─────────────────────────────────────────────
    elif data.startswith('play|'):
        _, group_str, card = data.split('|', 2)
        group_chat_id = int(group_str)
        game = games.get(group_chat_id)
        if not game or game.state != 'playing':
            await query.answer('No active game!', show_alert=True)
            return
        if 'wild' in card:
            try:
                await query.edit_message_reply_markup(color_keyboard(card))
            except Exception:
                pass
            await query.answer('Choose a color!')
            return
        result = game.play(user.id, card)
        await _resolve_play(result, user, card, game, group_chat_id, ctx, query)

    # ── COLOR PICK ────────────────────────────────────────────────────────
    elif data.startswith('color|'):
        _, card, chosen_color = data.split('|', 2)
        group_chat_id = player_chat.get(user.id)
        if not group_chat_id:
            await query.answer('Game not found!', show_alert=True)
            return
        game = games.get(group_chat_id)
        if not game:
            return
        result = game.play(user.id, card, chosen_color=chosen_color)
        await _resolve_play(result, user, card, game, group_chat_id, ctx, query)

    # ── NOOP ─────────────────────────────────────────────────────────────
    elif data == 'noop':
        await query.answer("This card can't be played right now!", show_alert=True)


# ══════════════════════════════════════════════════════════════════════════
# ─── Play result handler ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

async def _resolve_play(result: dict, user, card: str,
                        game: UnoGame, group_chat_id: int,
                        ctx: ContextTypes.DEFAULT_TYPE,
                        query):
    r = result.get('result')

    if r == 'not_your_turn':
        await query.answer("It's not your turn!", show_alert=True)
        return
    if r == 'invalid':
        await query.answer("You don't have that card!", show_alert=True)
        return
    if r == 'cannot_play':
        await query.answer("That card can't be played right now!", show_alert=True)
        return

    effect = result.get('effect')
    affected_name = result.get('affected_name', '')
    color_e = COLOR_EMOJI.get(game.current_color, '🌈')

    effect_lines = []
    if effect == 'draw2':
        effect_lines.append(f'💥 {affected_name} draws 2 cards and loses their turn!')
    elif effect == 'draw4':
        effect_lines.append(f'💥 {affected_name} draws 4 cards and loses their turn!')
    elif effect == 'skip':
        effect_lines.append('⏭️ Next player skipped!')
    elif effect == 'reverse':
        effect_lines.append('🔄 Direction reversed!')
    elif effect == 'wild':
        effect_lines.append(f'🌈 Color changed to {color_e} {game.current_color.capitalize()}!')

    effect_str = '\n' + '\n'.join(effect_lines) if effect_lines else ''

    # ── WIN ──────────────────────────────────────────────────────────────
    if r == 'win':
        pts = result.get('points', 0)
        try:
            await query.edit_message_text(
                f'🎉 *You won with {pts} points! Congrats!*'
                f'\nCheck the group for the final leaderboard.',
                parse_mode='Markdown',
            )
        except Exception:
            pass
        await _finish_game(ctx, game, group_chat_id, user.first_name, pts)
        return

    # ── GAME CONTINUES ────────────────────────────────────────────────────
    cur_uid, cur_name = game.current_player()
    uno_warn = ''
    if len(game.hands.get(cur_uid, [])) == 1:
        uno_warn = f'\n⚠️ *{cur_name}* has 1 card left!'

    group_text = (
        f'🃏 *{user.first_name}* played *{card_display(card)}*{effect_str}'
        f'\n\n{status_text(game)}{uno_warn}'
    )
    try:
        await ctx.bot.send_message(
            group_chat_id,
            group_text,
            parse_mode='Markdown',
            reply_markup=group_keyboard(),
        )
    except Exception as exc:
        logger.error('Group message error: %s', exc)

    # DM the next player their hand
    await _send_hand(ctx, game, cur_uid, group_chat_id)

    # Update the playing player's DM
    try:
        await query.edit_message_text(
            f'✅ Played *{card_display(card)}*{effect_str}\n\nWaiting for your next turn…',
            parse_mode='Markdown',
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# ─── Entry point ─────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler('start', cmd_start))
    app.add_handler(CommandHandler('newgame', cmd_newgame))
    app.add_handler(CommandHandler('scores', cmd_scores))
    app.add_handler(CommandHandler('endgame', cmd_endgame))
    app.add_handler(CallbackQueryHandler(handle_callback))

    if WEBHOOK_URL:
        logger.info('Starting with webhook: %s', WEBHOOK_URL)
        app.run_webhook(
            listen='0.0.0.0',
            port=PORT,
            url_path=TOKEN,
            webhook_url=f'{WEBHOOK_URL}/{TOKEN}',
        )
    else:
        logger.info('Starting with long-polling (local dev mode)')
        app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
