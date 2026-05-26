#!/usr/bin/env python3
"""Test direct Postgres connection to Supabase."""
import psycopg2

PASSWORD = "Centrum0501$Panadol"
REF = "rdhderpzkbhsargdvlvc"

regions = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "sa-east-1", "eu-west-1", "eu-west-2", "eu-central-1",
    "ap-southeast-1", "ap-northeast-1", "ca-central-1"
]

users = [f"postgres.{REF}", "postgres"]
ports = [6543, 5432]

for user in users:
    for region in regions:
        for port in ports:
            host = f"aws-0-{region}.pooler.supabase.com"
            try:
                conn = psycopg2.connect(
                    host=host, port=port, dbname="postgres",
                    user=user, password=PASSWORD,
                    connect_timeout=5, sslmode="require"
                )
                conn.autocommit = True
                cur = conn.cursor()
                cur.execute("SELECT current_database(), current_user")
                result = cur.fetchone()
                print(f"✅ CONNECTED! host={host} port={port} user={user}")
                print(f"   DB={result[0]}, User={result[1]}")
                conn.close()
                exit(0)
            except psycopg2.OperationalError as e:
                err = str(e).split("\n")[0][:100]
                if "password authentication failed" in err:
                    print(f"🔑 PASSWORD WRONG: {user}@{host}:{port}")
                elif "Tenant or user not found" in err:
                    pass  # silent, expected for wrong region
                elif "timeout" in err:
                    pass
                else:
                    print(f"❌ {err}")

print("\n❌ Could not connect to any pooler region.")
print("Fallback: Will use REST API approach.")
