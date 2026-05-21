#!/bin/bash
# Fraud Detection System - MacBook M2 Setup Script
# This script handles the setup process automatically

set -e  # Exit on any error

echo "🍎 Fraud Detection System - MacBook M2 Setup"
echo "=============================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Python 3 is not installed${NC}"
    echo "Please install Python 3 using:"
    echo "  brew install python@3.11"
    exit 1
fi

echo -e "${GREEN}✓${NC} Python 3 found: $(python3 --version)"

# Check if pip is available
if ! python3 -m pip --version &> /dev/null; then
    echo -e "${YELLOW}⚠️  pip not found, installing...${NC}"
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python3 get-pip.py --user
    rm get-pip.py
fi

echo -e "${GREEN}✓${NC} pip found: $(python3 -m pip --version)"

# Remove old broken venv if exists
if [ -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Removing old virtual environment...${NC}"
    rm -rf venv
fi

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "⬆️  Upgrading pip..."
python -m pip install --upgrade pip setuptools wheel

# Install dependencies
echo "📚 Installing dependencies..."
pip install -r requirements.txt

echo ""
echo -e "${GREEN}✅ Setup complete!${NC}"
echo ""
echo "To run the application:"
echo "  1. Activate the virtual environment:"
echo "     ${YELLOW}source venv/bin/activate${NC}"
echo ""
echo "  2. Run the application:"
echo "     ${YELLOW}python main.py${NC}"
echo ""
echo "  3. Open in browser:"
echo "     ${YELLOW}http://localhost:5000${NC}"
echo ""
echo "  4. Login with:"
echo "     Username: ${YELLOW}admin${NC}"
echo "     Password: ${YELLOW}admin123${NC}"
echo ""
echo "If port 5000 is in use (macOS AirPlay), use:"
echo "  ${YELLOW}python main.py --port 5050${NC}"
echo ""
