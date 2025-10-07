#!/bin/bash
# Quick test script to verify setup

echo "Drive Capture v2 - Setup Verification"
echo "======================================"
echo

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

# Test 1: Python
echo -n "1. Python installed: "
if command -v python3 &> /dev/null || command -v python &> /dev/null; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${RED}✗${NC}"
    ((FAIL++))
fi

# Test 2: Extension files
echo -n "2. Extension files: "
if [ -f "extension/manifest.json" ] && [ -f "extension/background.js" ]; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${RED}✗${NC}"
    ((FAIL++))
fi

# Test 3: Worker files
echo -n "3. Worker files: "
if [ -f "worker/worker.py" ] && [ -f "worker/launcher.sh" ]; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${RED}✗${NC}"
    ((FAIL++))
fi

# Test 4: Launcher executable
echo -n "4. Launcher executable: "
if [ -x "worker/launcher.sh" ]; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${RED}✗${NC}"
    ((FAIL++))
fi

# Test 5: Native messaging manifest
echo -n "5. Native manifest installed: "
MANIFEST_DIR="$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts"
if [ -f "$MANIFEST_DIR/com.drivecapture.worker.json" ]; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${YELLOW}? (run installer first)${NC}"
fi

# Test 6: Rclone
echo -n "6. Rclone available: "
if command -v rclone &> /dev/null; then
    echo -e "${GREEN}✓${NC}"
    ((PASS++))
else
    echo -e "${YELLOW}? (optional)${NC}"
fi

echo
echo "======================================"
echo "Results: $PASS passed, $FAIL failed"
echo

if [ $FAIL -eq 0 ]; then
    echo -e "${GREEN}✅ Setup looks good!${NC}"
    echo
    echo "Next step: Run ./setup/install.sh"
else
    echo -e "${RED}❌ Some issues found${NC}"
    echo
    echo "Please fix the issues above before continuing"
fi
