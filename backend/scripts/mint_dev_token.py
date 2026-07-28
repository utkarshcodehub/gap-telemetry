"""
Local-dev helper — NOT part of the running API on purpose. Mints a
throwaway token signed with AUTH_LOCAL_HS256_SECRET so you can call
protected endpoints with curl before you've wired up a real Supabase
project. This deliberately isn't an API endpoint: a "give me a token"
route is exactly the kind of thing that's fine in dev and dangerous if
it ever accidentally ships.

Usage (from backend/, with AUTH_LOCAL_HS256_SECRET set in .env):
    python3 scripts/mint_dev_token.py [user_id]

    curl -H "Authorization: Bearer $(python3 scripts/mint_dev_token.py)" \
         http://127.0.0.1:8000/analyses
"""

import os
import sys
import time
import uuid

import jwt
from dotenv import load_dotenv

load_dotenv()

secret = os.environ.get("AUTH_LOCAL_HS256_SECRET")
if not secret:
    print("AUTH_LOCAL_HS256_SECRET is not set in backend/.env", file=sys.stderr)
    sys.exit(1)

user_id = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
now = int(time.time())
token = jwt.encode(
    {"sub": user_id, "email": "dev@example.com", "aud": "authenticated",
     "iat": now, "exp": now + 3600},
    secret, algorithm="HS256",
)
print(token)
