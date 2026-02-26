import urllib.request, urllib.parse, json, sys, os

CLIENT_ID="28e94343-2f77-444c-ac32-58b7bed33b65"
TENANT_ID="caac06b5-1420-4223-9dcc-ba4a670ec26a"
REDIRECT_URI="https://login.microsoftonline.com/common/oauth2/nativeclient"
SCOPES="offline_access https://outlook.office.com/SMTP.Send https://outlook.office.com/IMAP.AccessAsUser.All"

if len(sys.argv) != 2:
    print("USAGE: python3 /root/exchange_code_to_refresh.py '<CODE>'")
    sys.exit(2)

CODE = sys.argv[1].strip()

data = urllib.parse.urlencode({
  "client_id": CLIENT_ID,
  "grant_type": "authorization_code",
  "code": CODE,
  "redirect_uri": REDIRECT_URI,
  "scope": SCOPES
}).encode()

url=f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
resp=json.loads(urllib.request.urlopen(urllib.request.Request(url, data=data)).read())

rt = resp.get("refresh_token","")
if not rt:
    print("ERROR: no refresh_token returned")
    print("scope_returned:", resp.get("scope"))
    sys.exit(1)

# store token locally (ONLY on VPS)
path="/root/.openclaw/azure_refresh_token.txt"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    f.write(rt)

print("scope_returned:", resp.get("scope"))
print("refresh_token_saved_to:", path)
print("refresh_token_length:", len(rt))
print("access_token_present:", bool(resp.get("access_token")))
