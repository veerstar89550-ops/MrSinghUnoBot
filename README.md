# 🎴 UNO Telegram Bot

Fully playable UNO bot for Telegram group chats — free to host on Render.com.

---

## Features
- 2–10 players per game
- Full UNO deck (Skip, Reverse, +2, Wild, Wild +4)
- Cards sent privately to each player via DM
- Leaderboard with cumulative scores and win counts
- UNO call & catch system
- Render.com webhook ready (free tier)

---

## Setup — Step by Step

### 1. Create your Telegram bot
1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Follow prompts → copy your **BOT_TOKEN**

### 2. Deploy to Render.com (free)
1. Push this folder to a **GitHub repo**
2. Go to [render.com](https://render.com) → **New → Web Service**
3. Connect your GitHub repo
4. Render auto-detects `render.yaml` — click **Apply**
5. In **Environment Variables**, add:
   - `BOT_TOKEN` = your token from BotFather
   - `WEBHOOK_URL` = your Render public URL  
     *(looks like `https://uno-telegram-bot.onrender.com`)*
6. Click **Deploy**

> ⚠️ Free Render instances sleep after 15 min of inactivity.  
> Use [UptimeRobot](https://uptimerobot.com) (free) to ping your URL every 5 min.

### 3. Local testing (optional)
```bash
pip install -r requirements.txt
export BOT_TOKEN=your_token_here
# Don't set WEBHOOK_URL — it will use long-polling automatically
python bot.py
```

---

## How to Play

### In a group chat:
| Command | What it does |
|---------|-------------|
| `/newgame` | Open a game lobby |
| `/scores` | Show leaderboard |
| `/endgame` | End the game (creator only) |

### Buttons during game:
| Button | Action |
|--------|--------|
| 🃏 My Cards (DM) | Get your hand sent to DM |
| ➕ Draw Card | Draw from the deck |
| 🔔 UNO! | Call UNO when you have 1 card |
| 😈 Catch UNO! | Penalize someone who forgot to call UNO |

### Steps for every player before joining:
1. Open your bot in DM (t.me/yourbotname)
2. Send `/start` — this allows the bot to DM you cards
3. Go back to the group → click **Join**

---

## Scoring (Official UNO rules)
| Card | Points |
|------|--------|
| Number cards | Face value (0–9) |
| Skip / Reverse / +2 | 20 pts |
| Wild / Wild +4 | 50 pts |

Winner gets points equal to the sum of all opponents' remaining cards.

---

## File Structure
```
uno_bot/
├── bot.py           # Telegram bot, commands, callbacks
├── uno_game.py      # Pure game logic (deck, rules, scoring)
├── requirements.txt
├── render.yaml      # Render.com deployment config
└── README.md
```
