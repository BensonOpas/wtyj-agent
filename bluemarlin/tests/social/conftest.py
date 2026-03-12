# bluemarlin/tests/social/conftest.py
# Created: Brief 067
# Last modified: Brief 071
# Purpose: Shared test config for social agent tests
import sys
import os
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..')))

# Set WhatsApp env vars before any module imports — whatsapp_client.py reads these
# at import time. Without this, test_067 importing webhook_server triggers
# whatsapp_client init with empty values, breaking test_068's send assertions.
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test_token_067")
os.environ.setdefault("WHATSAPP_ACCESS_TOKEN", "test_access_token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "990622044139349")
