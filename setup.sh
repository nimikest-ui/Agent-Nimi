#!/bin/bash
#
# AgentNimi - Setup Script
# Installs dependencies and configures the agent
#

set -e

RED='\033[91m'
GREEN='\033[92m'
YELLOW='\033[93m'
CYAN='\033[96m'
BOLD='\033[1m'
RESET='\033[0m'

echo -e "${RED}${BOLD}"
echo "  ╔═══════════════════════════════════════╗"
echo -e "  ║       ${CYAN}Agent-Nimi Setup${RED}               ║"
echo "  ╚═══════════════════════════════════════╝"
echo -e "${RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="$HOME/.agent-nimi"

# Check Python
echo -e "${CYAN}[1/4] Checking Python...${RESET}"
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version)
    echo -e "  ${GREEN}✓${RESET} $PY_VERSION"
else
    echo -e "  ${RED}✗ Python3 not found. Install it first.${RESET}"
    exit 1
fi

# Install pip dependencies
echo -e "${CYAN}[2/4] Installing Python dependencies...${RESET}"
pip3 install -r "$SCRIPT_DIR/requirements.txt" --quiet 2>/dev/null || \
    pip install -r "$SCRIPT_DIR/requirements.txt" --quiet
echo -e "  ${GREEN}✓${RESET} Dependencies installed"

# Create config directory
echo -e "${CYAN}[3/4] Setting up configuration...${RESET}"
mkdir -p "$CONFIG_DIR/logs"

if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo -e "  ${GREEN}✓${RESET} Config will be created on first run"
else
    echo -e "  ${GREEN}✓${RESET} Config exists at $CONFIG_DIR/config.json"
fi

# Create launcher script
echo -e "${CYAN}[4/4] Creating launcher...${RESET}"
LAUNCHER="/usr/local/bin/agent-nimi"
cat > /tmp/agent-nimi-launcher << EOF
#!/bin/bash
cd "$SCRIPT_DIR"
exec python3 main.py "\$@"
EOF

if [ "$(id -u)" -eq 0 ]; then
    mv /tmp/agent-nimi-launcher "$LAUNCHER"
    chmod +x "$LAUNCHER"
    echo -e "  ${GREEN}✓${RESET} Installed to ${LAUNCHER}"
    echo -e "  ${GREEN}  Run with: ${BOLD}agent-nimi${RESET}"
else
    LOCAL_LAUNCHER="$HOME/.local/bin/agent-nimi"
    mkdir -p "$HOME/.local/bin"
    mv /tmp/agent-nimi-launcher "$LOCAL_LAUNCHER"
    chmod +x "$LOCAL_LAUNCHER"
    echo -e "  ${GREEN}✓${RESET} Installed to ${LOCAL_LAUNCHER}"
    echo -e "  ${YELLOW}  Make sure ~/.local/bin is in your PATH${RESET}"
    echo -e "  ${GREEN}  Run with: ${BOLD}agent-nimi${RESET}"
fi

echo ""
echo -e "${GREEN}${BOLD}Setup complete!${RESET}"
echo ""
echo -e "${CYAN}Quick start:${RESET}"
echo -e "  ${BOLD}agent-nimi${RESET}                    # Start with Ollama (default)"
echo ""
echo -e "${CYAN}Provider setup:${RESET}"
echo -e "  Grok:        ${BOLD}/setkey <your-xai-key>${RESET} then ${BOLD}/provider grok${RESET}"
echo ""
