# Discord Server Manager Bot

A fully-featured Discord bot for automatically creating server structures, managing roles, moderation, and more. Built with **Python** and **discord.py**.

## Features

### 🏗️ Server Setup
- Apply pre-built YAML templates to instantly configure your server
- 3 built-in templates: **Gaming**, **Community**, **Minimal**
- Creates categories, channels, roles, and permission overwrites automatically
- Fully customizable templates — create your own!

### 👋 Welcome System
- Custom welcome messages with placeholders (`{user}`, `{server}`, `{member_count}`)
- Optional welcome DMs to new members
- Leave messages when members depart
- Auto-assign default roles on join

### 🎭 Reaction Roles
- Create reaction role messages with one command
- Add reaction roles to existing messages
- Auto-assign/remove roles when users react/unreact
- Persistent storage in SQLite

### 🔊 Auto Voice Channels
- Automatic private voice channel creation
- Join a "Create New" trigger channel to get your own private VC
- Auto-cleanup of empty channels
- Configurable limits and categories

### 🛡️ Moderation & Auto-Mod
- **Commands**: ban, kick, timeout, warn, clear messages
- **Auto-moderation**: spam detection, bad words filter, invite links, caps lock
- Configurable per-server
- Warning history tracking

### 📊 Leveling System
- XP earned per message with cooldown
- Level-up announcements in-channel
- Visual progress bars and leaderboards
- Auto-assign roles at specific levels
- Configurable XP amounts and cooldowns

### 🎫 Ticket System
- Create support tickets with one command
- Automatic private channel creation with proper permissions
- Ticket claiming for staff
- Transcript generation on close
- Interactive close button

### 📝 Logging
- Comprehensive server event logging
- Messages deleted/edited, role changes, nickname changes
- Moderation action tracking
- Configurable log channel

## Project Structure

```
discord-bot/
├── main.py                    # Entry point
├── requirements.txt           # Python dependencies
├── .env.example              # Environment template
├── .gitignore
├── bot/
│   ├── __init__.py
│   ├── client.py              # Bot client & event handling
│   ├── config.py              # Configuration management
│   ├── database.py            # Async SQLite database
│   └── cogs/
│       ├── setup.py           # Template-based server setup
│       ├── welcome.py         # Welcome/leave messages
│       ├── roles.py           # Reaction roles
│       ├── channels.py        # Auto voice channels
│       ├── moderation.py      # Moderation & auto-mod
│       ├── logging_cog.py     # Event logging
│       ├── leveling.py        # XP & leveling
│       ├── tickets.py         # Support tickets
│       └── help.py            # Help & info commands
└── templates/
    ├── __init__.py
    ├── loader.py              # YAML template loader
    └── defaults/
        ├── gaming.yaml        # Gaming server template
        ├── community.yaml     # Community server template
        └── minimal.yaml       # Minimal server template
```

## Setup

### Prerequisites
- Python 3.10+
- A Discord Bot token ([Create one here](https://discord.com/developers/applications))

### Installation

1. **Clone the project:**
   ```bash
   git clone <repository-url>
   cd discord-bot
   ```

2. **Create a virtual environment:**
   ```bash
   python -m venv venv
   venv\Scripts\activate    # Windows
   # source venv/bin/activate  # Linux/Mac
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure the bot:**
   ```bash
   copy .env.example .env    # Windows
   # cp .env.example .env    # Linux/Mac
   ```
   Edit `.env` and add your bot token:
   ```
   BOT_TOKEN=your_bot_token_here
   OWNER_ID=your_discord_user_id
   PREFIX=!
   DATA_PATH=./data/bot.db
   ```

5. **Enable Privileged Intents** in the Discord Developer Portal:
   - Go to your bot's settings
   - Enable **Message Content Intent**
   - Enable **Server Members Intent**

6. **Run the bot:**
   ```bash
   python main.py
   ```

## Usage

### Basic Commands

| Command | Description |
|---------|-------------|
| `/help` | Display all available commands |
| `/ping` | Check bot latency |
| `/botinfo` | Display bot information |

### Server Setup

| Command | Description |
|---------|-------------|
| `/setup <template>` | Apply a server template (gaming/community/minimal) |
| `/templates` | List available templates |

### Welcome

| Command | Description |
|---------|-------------|
| `/welcome-channel <#ch>` | Set welcome channel |
| `/welcome-message <msg>` | Set welcome message |
| `/welcome-toggle <true/false>` | Enable/disable |
| `/welcome-dm <msg>` | Set welcome DM |
| `/leave-channel` / `/leave-message` | Configure leave messages |

### Reaction Roles

| Command | Description |
|---------|-------------|
| `/reactionrole create` | Create a new reaction role message |
| `/reactionrole-add` | Add to existing message |
| `/reactionrole-list` | List all reaction roles |
| `/reactionrole-delete <id>` | Remove a reaction role |

### Auto Voice

| Command | Description |
|---------|-------------|
| `/voice-auto-toggle <true/false>` | Enable/disable |
| `/voice-auto-limit <n>` | Set max auto channels |
| `/voice-auto-category <#cat>` | Set target category |
| `/voice-auto-trigger` | Create trigger channel |

### Moderation

| Command | Description |
|---------|-------------|
| `/mod-ban` / `/mod-kick` / `/mod-mute` | Moderation actions |
| `/mod-warn` / `/mod-warnings` | Warning system |
| `/mod-clear` | Bulk delete messages |
| `/automod-setup` | Setup auto-moderation |
| `/automod-toggle` | Enable/disable auto-mod |
| `/automod-words-add/remove/list` | Manage bad words |

### Leveling

| Command | Description |
|---------|-------------|
| `/level [@user]` | Check level |
| `/leaderboard` | View leaderboard |
| `/leveling-reward <lvl> <role>` | Set level rewards |
| `/leveling-xp` / `/leveling-cooldown` | Configure XP |

### Tickets

| Command | Description |
|---------|-------------|
| `/ticket-create` | Create a ticket |
| `/ticket-close` | Close current ticket |
| `/ticket-claim` | Claim a ticket (staff) |
| `/ticket-setup` | Configure ticket system |

### Logging

| Command | Description |
|---------|-------------|
| `/logging-setup <#channel>` | Set log channel |
| `/logging-view` | View logging status |

## Creating Custom Templates

Create a `.yaml` file in `templates/defaults/`:

```yaml
name: "My Custom Server"
description: "A custom server template"

categories:
  - name: "general"
    channels:
      - name: "chat"
        type: text
      - name: "Voice"
        type: voice

roles:
  - name: "VIP"
    color: 15844367
    mentionable: true

welcome:
  channel: "general"
  message: "Welcome {user} to {server}!"
```

## License

MIT License