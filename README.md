Telegram Auto Caption Bot
A Pyrogram + MongoDB bot that lets channel owners auto-format captions on channels they administer: templated captions, header/footer/watermark text, and owner-defined word replace/remove rules for their own content.
Scope note: the bot only edits messages in channels where (a) the channel owner explicitly added the bot through the in-bot Add Channel flow, and (b) the bot's own get_chat_member check confirms it is an actual admin of that channel. It will not act on any other chat.
Project Structure
telegram_caption_bot/
├── main.py                  # entry point
├── config.py                 # env-based configuration
├── requirements.txt
├── .env.example
├── database/
│   ├── mongo.py               # Motor client / collections
│   ├── users.py                # user CRUD
│   └── channels.py             # channel + settings CRUD
├── plugins/
│   ├── start.py                 # /start, force-subscribe
│   ├── menu.py                    # main menu navigation
│   ├── add_channel.py              # Add Channel flow
│   ├── edit_channel.py              # Edit Channel management panel
│   ├── auto_caption.py               # live caption rewriting on new posts
│   ├── stats.py                       # statistics panel
│   ├── backup.py                       # export/import channel config
│   └── broadcast.py                     # /broadcast to all users
└── utils/
    ├── logger.py
    ├── filters.py                # admin_only filter
    ├── state.py                   # in-memory multi-step conversation state
    ├── keyboards.py                 # inline keyboard layouts
    └── caption_builder.py            # variable substitution / replace / remove engine
Setup
1. Prerequisites
Python 3.11+
A running MongoDB instance (local, Docker, or Atlas free tier)
Telegram API credentials from https://my.telegram.org
A bot token from @BotFather
2. Install
git clone <your-repo-url>
cd telegram_caption_bot
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
3. Configure
cp .env.example .env
# edit .env with your API_ID, API_HASH, BOT_TOKEN, MONGO_URI, ADMINS, etc.
ADMINS is a comma-separated list of Telegram numeric user IDs allowed to use the management panel. Get your own ID from @userinfobot.
4. Run
python3 main.py
Using the Bot
Admin sends /start in a private chat with the bot.
Add Channel: add the bot as admin in your Telegram channel, then forward any message from that channel to the bot. It verifies its own admin status before saving anything.
Edit Channel: pick a channel, then configure:
Auto Caption ON/OFF
Caption Template (with {filename}, {filesize}, {duration}, {caption}, {default_caption}, {channel_name}, {channel_username}, {message_id}, {date}, {time})
Header / Footer / Watermark text
Word Replace rules (find → replace, for your own captions)
Word Remove list (delete a phrase from your own captions)
Preview (renders against sample data before you enable it)
Reset Settings
Once Auto Caption is ON, every new photo/video/GIF/document/audio/ voice/video note/animation/text message posted in that channel is automatically reformatted per the saved settings.
HTML formatting
Templates, headers, footers, and watermarks all support Telegram HTML: <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">, and expandable blockquotes:
<blockquote expandable>
Full details here, collapsed by default.
</blockquote>
Admin utilities
Statistics: total users, channels, and edited-message count.
Backup/Restore: export a channel's settings to a JSON file and import it into another channel you own.
Broadcast: /broadcast <text> (or reply to a message with /broadcast) sends it to every user who has started the bot.
Deployment
Docker
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python3", "main.py"]
docker build -t caption-bot .
docker run -d --env-file .env --name caption-bot caption-bot
VPS (systemd)
# /etc/systemd/system/caption-bot.service
[Unit]
Description=Telegram Auto Caption Bot
After=network.target mongod.service

[Service]
WorkingDirectory=/opt/caption-bot
ExecStart=/opt/caption-bot/venv/bin/python3 main.py
Restart=always
EnvironmentFile=/opt/caption-bot/.env

[Install]
WantedBy=multi-user.target
sudo systemctl enable --now caption-bot
Known limitations / next steps
Conversation state (utils/state.py) is in-memory and per-process. Running multiple bot instances behind a load balancer requires swapping it for a shared store (e.g. Redis) keyed the same way.
auto_caption_handler edits messages after they're posted (via edit_caption/edit_text), which is the only mechanism Pyrogram/Bot API offers for channel posts made directly in Telegram's UI. If you also want to intercept messages before they're first published, that requires the channel owner to post through the bot instead of directly.
No pagination on channel lists — fine for a handful of channels per user; add pagination to channel_list() if a single user manages dozens.