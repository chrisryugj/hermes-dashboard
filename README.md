# Hermes Dashboard

Web-based admin dashboard for [Hermes Agent](https://github.com/NousResearch/hermes-agent) gateway. Full configuration and control without CLI.

![Dashboard](https://img.shields.io/badge/hermes-dashboard-5e6ad2?style=flat-square) ![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)

## Features

| Category | Capabilities |
|----------|-------------|
| **Overview** | Gateway status, model info, platform connections, MCP servers, cron summary, auth status, disk usage |
| **Model** | Switch LLM model + provider with one click (auto-restart) |
| **MCP** | Add / edit / delete MCP servers. **Paste Config**: import Claude Desktop / Cursor / VS Code MCP JSON directly |
| **Cron** | Create / edit / delete / pause / resume / run-now cron jobs. Delivery target management |
| **Skills** | Browse 95+ skills by category. Search. View SKILL.md detail |
| **Config** | Edit `config.yaml` with full JSON editor |
| **Env** | Edit `.env` variables. Secrets auto-masked. Add new variables |
| **Soul** | Edit `SOUL.md` persona |
| **Logs** | View gateway logs in real-time. Clear logs |
| **Sessions** | Browse and delete sessions |
| **System** | Gateway restart with health polling. Restart-needed banner on config changes |

### Design

- Linear-inspired dark theme (`#08090a` canvas, Inter font, `cv01` + `ss03` OpenType features)
- All dialogs are dark-themed custom modals (no native `prompt()`/`confirm()`)
- Single HTML file, no build step, no dependencies

### Security

- Path traversal prevention on all file operations
- Atomic file writes (temp file + `os.replace`)
- XSS protection (HTML entity + single-quote escaping)
- Secret auto-masking (TOKEN/KEY/SECRET/PASSWORD patterns)
- Input validation on all endpoints (regex-based)
- Referrer policy (`no-referrer`) to prevent API key leakage

## Installation

### Quick Install

```bash
git clone https://github.com/chrisryugj/hermes-dashboard.git
cd hermes-dashboard
./install.sh
```

The installer:
1. Copies dashboard files to `~/.hermes/dashboard/`
2. Patches `api_server.py` to register dashboard routes
3. Enables API server in `.env`

Then restart your gateway:
```bash
# launchd
launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway

# or manual
hermes gateway restart
```

Access: **http://localhost:8642/dashboard**

### Manual Install

1. Copy files:
```bash
mkdir -p ~/.hermes/dashboard
cp hermes_dashboard/api.py ~/.hermes/dashboard/
cp hermes_dashboard/index.html ~/.hermes/dashboard/
```

2. Add to `~/.hermes/.env`:
```
API_SERVER_ENABLED=true
API_SERVER_PORT=8642
```

3. Patch `api_server.py` (find `# Start background sweep` line and add before it):
```python
# Dashboard plugin
try:
    import sys as _sys
    _hermes_home = os.path.expanduser("~/.hermes")
    if os.path.join(_hermes_home, "dashboard") not in _sys.path:
        _sys.path.insert(0, os.path.join(_hermes_home, "dashboard"))
    from api import register_dashboard_routes
    register_dashboard_routes(self._app)
    logger.info("[%s] Dashboard registered at /dashboard", self.name)
except Exception as _dash_err:
    logger.debug("[%s] Dashboard not loaded: %s", self.name, _dash_err)
```

### Authentication

Set `API_SERVER_KEY` in `.env` for token-based auth:
```
API_SERVER_KEY=your-secret-key
```

Access with: `http://localhost:8642/dashboard?key=your-secret-key`

### macOS Menu Bar Monitor (Optional)

```bash
pip install rumps
python3 ~/.hermes/dashboard/monitor.py
```

Shows gateway status in macOS menu bar with quick actions (dashboard, restart, logs).

## Supported Models

The model selector supports these providers:

| Provider | Models |
|----------|--------|
| **OpenAI Codex** | gpt-5.4, gpt-5.4-mini, gpt-5.3-codex, gpt-5.2-codex, gpt-5.1-codex-mini/max |
| **Anthropic** | claude-opus-4-6, claude-sonnet-4-6, claude-opus-4-5, claude-sonnet-4-5, claude-haiku-4-5 |
| **Google Gemini** | gemini-3.1-pro-preview, gemini-3-flash-preview, gemini-2.5-pro/flash/flash-lite |
| **DeepSeek** | deepseek-chat, deepseek-reasoner |
| **xAI Grok** | grok-4.20, grok-4.1-fast, grok-code-fast-1, grok-3 |
| **OpenRouter** | Any model via aggregator |
| **Nous Portal** | Any model via aggregator |
| **GitHub Copilot** | gpt-5.4, claude-sonnet-4.6, gemini-2.5-pro |

## MCP Server Setup

### Paste Config (Easiest)

Click **Paste Config** and paste your existing MCP config from Claude Desktop, Cursor, or VS Code:

```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["/path/to/server/index.js"],
      "env": { "API_KEY": "xxx" }
    }
  }
}
```

All formats accepted: `mcpServers`, `mcp_servers`, or direct server objects.

### Manual Add

Click **+ Add** and fill in name, command, args (JSON array), and optional env (JSON object).

## Requirements

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) v0.7.0+
- Python 3.10+ with PyYAML and aiohttp (included with Hermes)
- macOS menu bar monitor requires [rumps](https://github.com/jaredks/rumps) (`pip install rumps`)

## License

MIT
