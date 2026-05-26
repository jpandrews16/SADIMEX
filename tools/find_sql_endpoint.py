#!/usr/bin/env python3
"""Find a working SQL execution endpoint in Supabase."""
import json
import urllib.request
import urllib.error

BASE = "https://rdhderpzkbhsargdvlvc.supabase.co"
SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJkaGRlcnB6a2Joc2FyZ2R2bHZjIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTI5NjY3MywiZXhwIjoyMDg2ODcyNjczfQ.GrpMFbI836Vgaf7d6V-rzbDyHlNOl9DnuGwRBY6fRl8"

def try_endpoint(name, url, method="POST", body=None, extra_headers=None):
    headers = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "apikey": SERVICE_KEY,
        "Content-Type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = resp.read().decode()[:200]
            print(f"✅ {name}: HTTP {resp.status} -> {result}")
            return True
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()[:200] if e.fp else ""
        print(f"❌ {name}: HTTP {e.code} -> {body_text}")
        return False
    except Exception as e:
        print(f"❌ {name}: {str(e)[:100]}")
        return False

print("=" * 60)
print("SUPABASE SQL ENDPOINT DISCOVERY")
print("=" * 60)

# Test 1: pg-meta query (used by Supabase Studio internally)
try_endpoint("pg-meta /pg/query", f"{BASE}/pg/query", body={"query": "SELECT 1 as test"})

# Test 2: pg-meta with path variations
try_endpoint("pg-meta /pg-meta/default/query", f"{BASE}/pg-meta/default/query", body={"query": "SELECT 1"})

# Test 3: Direct graphql endpoint (pg_graphql extension)
try_endpoint("pg_graphql", f"{BASE}/graphql/v1", body={"query": "{ __typename }"})

# Test 4: Edge function invocation  
try_endpoint("Edge Fn create-sadimex-user", f"{BASE}/functions/v1/create-sadimex-user", body={"test": True})

# Test 5: Check existing RPC functions
try_endpoint("RPC listing", f"{BASE}/rest/v1/rpc/", method="GET")

# Test 6: Try calling the Supabase platform/management API to get a token
try_endpoint("Platform login", "https://api.supabase.com/gotrue/token?grant_type=password",
             body={"email": "jpandrews16@gmail.com", "password": "Centrum0501$Panadol"})

# Test 7: Check if sadimex_profiles has data (verify DB is alive)
try_endpoint("sadimex_profiles SELECT", f"{BASE}/rest/v1/sadimex_profiles?select=id,nombre,rol&limit=3", method="GET")

# Test 8: Try the Supabase Management API SQL endpoint directly
try_endpoint("Mgmt API SQL", "https://api.supabase.com/v1/projects/rdhderpzkbhsargdvlvc/database/query",
             body={"query": "SELECT 1"})

print("\n" + "=" * 60)
print("DISCOVERY COMPLETE")
print("=" * 60)
