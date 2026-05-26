#!/usr/bin/env python3
"""Quick endpoint tests with short timeouts."""
import json
import urllib.request
import urllib.error

BASE = "https://rdhderpzkbhsargdvlvc.supabase.co"
SK = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJkaGRlcnB6a2Joc2FyZ2R2bHZjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTI5NjY3MywiZXhwIjoyMDg2ODcyNjczfQ.GrpMFbI836Vgaf7d6V-rzbDyHlNOl9DnuGwRBY6fRl8"

def test(name, url, method="GET", body=None):
    h = {"Authorization": f"Bearer {SK}", "apikey": SK, "Content-Type": "application/json"}
    d = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=d, headers=h, method=method)
    try:
        resp = urllib.request.urlopen(r, timeout=5)
        txt = resp.read().decode()[:300]
        print(f"✅ {name}: {resp.status} -> {txt[:200]}")
        return txt
    except urllib.error.HTTPError as e:
        b = e.read().decode()[:200] if e.fp else ""
        print(f"❌ {name}: {e.code} -> {b}")
        return None
    except Exception as e:
        print(f"⏱️ {name}: {str(e)[:80]}")
        return None

# 1. Verify DB is alive — read existing table
print("=== 1. DB ALIVE CHECK ===")
result = test("profiles", f"{BASE}/rest/v1/sadimex_profiles?select=id,nombre,rol,ciudad&limit=3")

# 2. Check GraphQL (pg_graphql)
print("\n=== 2. GRAPHQL ===")
test("graphql", f"{BASE}/graphql/v1", "POST", {"query": "{ __typename }"})

# 3. Edge function
print("\n=== 3. EDGE FUNCTION ===")
test("edge-fn", f"{BASE}/functions/v1/create-sadimex-user", "POST", {"test": True})

# 4. Platform login
print("\n=== 4. PLATFORM API ===")
test("platform", "https://api.supabase.com/v1/projects", "GET")

print("\nDone!")
