# 小朱诺诺 — Overwatch 2 Discord Bot

<div align="center">

**守望先锋 2 Discord 数据查询机器人**

[中文](#中文说明) | [English](#english)

</div>

---

## 中文说明

### 功能一览

| 指令 | 说明 |
|------|------|
| `/register <BattleTag>` | 绑定你的暴雪战网 ID |
| `/unregister` | 解除绑定 |
| `/stats [成员] [模式]` | 查看已绑定玩家的详细战绩 |
| `/lookup <BattleTag> [模式]` | 直接查询任意玩家战绩（无需注册） |
| `/hero <英雄> [成员]` | 查看某个英雄的详细数据（含专属技能数据） |
| `/leaderboard` | 服务器竞技排行榜 |
| `/stadium <英雄>` | 查询决斗领域 Top 5 Build Codes |
| `/id add <BattleTag> [备注]` | 保存一个战网 ID（最多 10 个） |
| `/id list` | 查看已保存的所有 ID |
| `/id share <BattleTag>` | 在频道中公开分享某个 ID |
| `/id remove <BattleTag>` | 删除已保存的 ID |

- **模式选择**：`/stats` 和 `/lookup` 支持 `全部`、`竞技` 、`快速` 三种模式
- **中文英雄名**：`/hero` 和 `/stadium` 均支持中英文英雄名称及自动补全
- **隐私友好**：`/id` 系列指令不调用 API，即使游戏资料设为私密也可正常使用

### 如何添加到你的服务器

#### 1. 创建 Discord 应用

1. 前往 [Discord Developer Portal](https://discord.com/developers/applications)
2. 点击 **New Application**，输入名称
3. 进入 **Bot** 页面，点击 **Reset Token**，复制并保存 Bot Token
4. 关闭 **Public Bot**（防止他人邀请你的 Bot）
5. 开启 **Server Members Intent**

#### 2. 生成邀请链接

1. 进入 **OAuth2** 页面
2. 在 **OAuth2 URL Generator** 中勾选：
   - Scopes: `bot`、`applications.commands`
   - Bot Permissions: `Send Messages`、`Embed Links`、`Use Slash Commands`
3. 复制生成的链接，在浏览器中打开
4. 选择你要添加的服务器，点击授权

#### 3. 部署 Bot

**本地开发：**

```bash
git clone https://github.com/aquamarinz/ow2-discord-bot.git
cd ow2-discord-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，填入你的 DISCORD_TOKEN
python main.py
```

**Railway 部署（推荐）：**

1. Fork 本仓库到你的 GitHub
2. 前往 [Railway](https://railway.com)，新建项目，选择 **Deploy from GitHub repo**
3. 添加 **PostgreSQL** 插件
4. 在 worker 服务的 **Variables** 中设置环境变量（见下方）
5. 首次部署时设置 `SYNC_COMMANDS=1`，部署成功后删除该变量

### 环境变量配置

| 变量名 | 必需 | 说明 |
|--------|------|------|
| `DISCORD_TOKEN` | ✅ | Discord Bot Token |
| `DATABASE_URL` | 生产环境 | PostgreSQL 连接字符串（Railway 自动设置） |
| `DATABASE_PATH` | 本地开发 | SQLite 文件路径（默认 `ow_bot.db`） |
| `OVERFAST_API_BASE` | ❌ | OverFast API 地址（默认 `https://overfast-api.tekrop.fr`） |
| `OWAPI_FALLBACK_BASE` | ❌ | 备用 API 地址（默认 `https://owapi.eu`） |
| `SUPABASE_STADIUM_URL` | `/stadium` 功能需要 | Supabase RPC 端点 |
| `SUPABASE_STADIUM_KEY` | `/stadium` 功能需要 | Supabase anon key |
| `SYNC_COMMANDS` | 仅首次 | 设为 `1` 以注册斜杠命令，之后删除 |

> **Railway 用户**：`DATABASE_URL` 设为 `${{Postgres.DATABASE_URL}}` 即可自动引用。

### 项目结构

```
ow_bot/
├── main.py              # 入口，Bot 初始化
├── config.py            # 配置常量
├── database.py          # 数据库（PostgreSQL / SQLite 双后端）
├── requirements.txt     # 依赖
├── cogs/
│   ├── registration.py  # /register, /unregister
│   ├── stats.py         # /stats, /lookup
│   ├── leaderboard.py   # /leaderboard
│   ├── stadium.py       # /stadium
│   ├── identity.py      # /id add|list|share|remove
│   └── hero.py          # /hero
├── api/
│   └── client.py        # OverFast API 客户端
└── utils/
    ├── embeds.py        # Discord Embed 构建 + 英雄中文名数据
    └── scoring.py       # 排行榜排序逻辑
```

### 注意事项

- **游戏资料需公开**：`/stats`、`/lookup`、`/hero` 依赖 OverFast API，玩家需在游戏内将职业生涯资料设为"公开"
- **斜杠命令同步**：新增或修改命令后，需设置 `SYNC_COMMANDS=1` 并重启一次
- **排行榜缓存**：排行榜数据缓存 5 分钟，避免频繁 API 调用

---

## English

### Commands

| Command | Description |
|---------|-------------|
| `/register <BattleTag>` | Link your Battle.net account |
| `/unregister` | Unlink your account |
| `/stats [member] [mode]` | View detailed stats for a registered player |
| `/lookup <BattleTag> [mode]` | Look up any player's stats (no registration needed) |
| `/hero <hero> [member]` | View hero-specific stats with unique ability data |
| `/leaderboard` | Server competitive rankings |
| `/stadium <hero>` | Top 5 Stadium mode build codes |
| `/id add <BattleTag> [label]` | Save a BattleTag (up to 10 per server) |
| `/id list` | View your saved accounts |
| `/id share <BattleTag>` | Share a specific account publicly |
| `/id remove <BattleTag>` | Remove a saved account |

- **Mode selection**: `/stats` and `/lookup` support `all`, `competitive`, and `quickplay`
- **Bilingual heroes**: `/hero` and `/stadium` accept both Chinese and English hero names with autocomplete
- **Privacy-friendly**: `/id` commands don't call any API — works even if your profile is private

### Adding the Bot to Your Server

#### 1. Create a Discord Application

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **New Application** and name it
3. Go to **Bot** → **Reset Token** → copy and save the token
4. Turn off **Public Bot** (prevents others from inviting your bot)
5. Enable **Server Members Intent**

#### 2. Generate an Invite Link

1. Go to **OAuth2** page
2. Under **OAuth2 URL Generator**, select:
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Use Slash Commands`
3. Copy the generated URL, open it in your browser
4. Select your server and authorize

#### 3. Deploy

**Local development:**

```bash
git clone https://github.com/aquamarinz/ow2-discord-bot.git
cd ow2-discord-bot
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env and set your DISCORD_TOKEN
python main.py
```

**Railway (recommended for production):**

1. Fork this repo to your GitHub account
2. Go to [Railway](https://railway.com), create a new project, select **Deploy from GitHub repo**
3. Add a **PostgreSQL** plugin
4. Set environment variables in the worker service's **Variables** tab (see below)
5. Set `SYNC_COMMANDS=1` for the first deploy, then remove it

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | ✅ | Your Discord bot token |
| `DATABASE_URL` | Production | PostgreSQL connection string (auto-set on Railway) |
| `DATABASE_PATH` | Local dev | SQLite file path (default: `ow_bot.db`) |
| `OVERFAST_API_BASE` | ❌ | OverFast API URL (default: `https://overfast-api.tekrop.fr`) |
| `OWAPI_FALLBACK_BASE` | ❌ | Fallback API URL (default: `https://owapi.eu`) |
| `SUPABASE_STADIUM_URL` | For `/stadium` | Supabase RPC endpoint |
| `SUPABASE_STADIUM_KEY` | For `/stadium` | Supabase anon key |
| `SYNC_COMMANDS` | First deploy only | Set to `1` to register slash commands, then remove |

> **Railway users**: Set `DATABASE_URL` to `${{Postgres.DATABASE_URL}}` for automatic reference.

### Project Structure

```
ow_bot/
├── main.py              # Entry point, bot initialization
├── config.py            # Configuration constants
├── database.py          # Database layer (PostgreSQL / SQLite)
├── requirements.txt     # Dependencies
├── cogs/
│   ├── registration.py  # /register, /unregister
│   ├── stats.py         # /stats, /lookup
│   ├── leaderboard.py   # /leaderboard
│   ├── stadium.py       # /stadium
│   ├── identity.py      # /id add|list|share|remove
│   └── hero.py          # /hero
├── api/
│   └── client.py        # OverFast API client with fallback
└── utils/
    ├── embeds.py        # Discord embed builders + hero name database
    └── scoring.py       # Leaderboard ranking logic
```

### Notes

- **Public profile required**: `/stats`, `/lookup`, and `/hero` rely on the OverFast API — players must set their career profile to "Public" in-game
- **Command sync**: After adding or modifying commands, set `SYNC_COMMANDS=1` and restart once
- **Leaderboard cache**: Leaderboard data is cached for 5 minutes to reduce API calls

---

### Tech Stack

- **[discord.py](https://discordpy.readthedocs.io/)** — Discord bot framework
- **[OverFast API](https://overfast-api.tekrop.fr)** — Overwatch 2 player data
- **[stadiumbuilds.io](https://stadiumbuilds.io)** — Stadium mode build codes
- **PostgreSQL** / **SQLite** — Dual database backend
- **[Railway](https://railway.com)** — Cloud deployment

### License

MIT
