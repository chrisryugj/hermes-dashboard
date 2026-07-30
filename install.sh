#!/bin/bash
# Hermes Dashboard Installer
# Copies dashboard files to ~/.hermes/dashboard/ and patches api_server.py

set -e

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DASHBOARD_DIR="$HERMES_HOME/dashboard"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/hermes_dashboard"

echo "Hermes Dashboard Installer"
echo "=========================="
echo ""

# Check hermes exists
if [ ! -d "$HERMES_HOME" ]; then
  echo "Error: $HERMES_HOME not found. Install Hermes Agent first."
  exit 1
fi

# Copy dashboard files
echo "Installing dashboard to $DASHBOARD_DIR ..."
mkdir -p "$DASHBOARD_DIR"
cp "$SRC/api.py" "$DASHBOARD_DIR/api.py"
cp "$SRC/index.html" "$DASHBOARD_DIR/index.html"
cp "$SRC/monitor.py" "$DASHBOARD_DIR/monitor.py"
echo "  Copied api.py, index.html, monitor.py"

# Patch api_server.py if not already patched
API_SERVER=""
for candidate in \
  "$HERMES_HOME/../hermes-agent/gateway/platforms/api_server.py" \
  "$(pip show hermes-agent 2>/dev/null | grep Location | cut -d' ' -f2)/gateway/platforms/api_server.py" \
  "$(python3 -c 'import hermes_cli; import os; print(os.path.dirname(hermes_cli.__file__))' 2>/dev/null)/../gateway/platforms/api_server.py"
do
  if [ -f "$candidate" ]; then
    API_SERVER="$candidate"
    break
  fi
done

if [ -z "$API_SERVER" ]; then
  # Try common locations
  for loc in /tmp/hermes-agent ~/.local/lib/python*/site-packages/hermes-agent; do
    f="$loc/gateway/platforms/api_server.py"
    if [ -f "$f" ]; then
      API_SERVER="$f"
      break
    fi
  done
fi

if [ -n "$API_SERVER" ] && ! grep -q "register_dashboard_routes" "$API_SERVER"; then
  echo "Patching $API_SERVER ..."
  # Find the line with "# Start background sweep" and insert dashboard plugin before it
  PATCH='            # Dashboard plugin\
            try:\
                import sys as _sys\
                _hermes_home = os.path.expanduser("~/.hermes")\
                if os.path.join(_hermes_home, "dashboard") not in _sys.path:\
                    _sys.path.insert(0, os.path.join(_hermes_home, "dashboard"))\
                from api import register_dashboard_routes\
                register_dashboard_routes(self._app)\
                logger.info("[%s] Dashboard registered at /dashboard", self.name)\
            except Exception as _dash_err:\
                logger.debug("[%s] Dashboard not loaded: %s", self.name, _dash_err)'

  if grep -q "# Start background sweep" "$API_SERVER"; then
    sed -i.bak "/# Start background sweep/i\\
$PATCH
" "$API_SERVER"
    echo "  Patched successfully"
  else
    echo "  Warning: Could not find patch point. Manual patch needed."
    echo "  Add the following to APIServerAdapter.connect() in api_server.py:"
    echo "  $PATCH"
  fi
elif [ -n "$API_SERVER" ]; then
  echo "  api_server.py already patched"
else
  echo "  Warning: api_server.py not found. See README for manual setup."
fi

# Enable API server in .env if not already
ENV_FILE="$HERMES_HOME/.env"
if [ -f "$ENV_FILE" ]; then
  if ! grep -q "API_SERVER_ENABLED" "$ENV_FILE"; then
    echo "" >> "$ENV_FILE"
    echo "API_SERVER_ENABLED=true" >> "$ENV_FILE"
    echo "API_SERVER_PORT=8642" >> "$ENV_FILE"
    echo "  Added API_SERVER_ENABLED=true to .env"
  fi
else
  echo "API_SERVER_ENABLED=true" > "$ENV_FILE"
  echo "API_SERVER_PORT=8642" >> "$ENV_FILE"
  echo "  Created .env with API_SERVER_ENABLED=true"
fi

echo ""
echo "Done! Restart your Hermes gateway to activate the dashboard."
echo ""
echo "  Access: http://localhost:8642/dashboard"
echo ""
echo "Required: Set API_SERVER_KEY in .env — dashboard APIs return 503 without it:"
echo "  echo 'API_SERVER_KEY=your-secret-key' >> $ENV_FILE"
echo ""
echo "Optional: Install macOS menu bar monitor (requires rumps):"
echo "  pip install rumps"
echo "  python3 $DASHBOARD_DIR/monitor.py"
