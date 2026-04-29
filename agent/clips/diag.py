import os, httpx, json
from dotenv import load_dotenv
load_dotenv()

r = httpx.get(
    'https://api.vapi.ai/call/019ddb18-d683-7000-99b1-8a01bb070c83',
    headers={'Authorization': f'Bearer {os.environ["VAPI_API_KEY"]}'},
    timeout=15,
)
data = r.json()
print('=== latest call ===')
print('status:', data.get('status'))
print('endedReason:', data.get('endedReason'))
print('startedAt:', data.get('startedAt'))
print('endedAt:', data.get('endedAt'))
print('cost:', data.get('cost'))

msgs = data.get('messages', [])
print('messages:', len(msgs))
for m in msgs[:25]:
    role = m.get('role', '?')
    msg = m.get('message', '')
    if msg:
        print(f'  [{role}] {msg[:140]}')

print()
print('=== recent calls ===')
r2 = httpx.get('https://api.vapi.ai/call?limit=8',
    headers={'Authorization': f'Bearer {os.environ["VAPI_API_KEY"]}'}, timeout=15)
calls = r2.json() if r2.status_code == 200 else []
for c in calls[:8]:
    print('  ', c.get('createdAt','?')[:19],
          c.get('status','?'),
          'ended:', c.get('endedReason','-'),
          'cost:', c.get('cost', 0))
