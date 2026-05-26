import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { Pool } from "https://deno.land/x/postgres@v0.19.3/mod.ts";

Deno.serve(async (req: Request) => {
  try {
    // Verify authorization with service role key
    const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
    const authHeader = req.headers.get("Authorization");
    if (!authHeader || !authHeader.includes(serviceRoleKey)) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }

    const body = await req.json();
    const sql = body.sql;

    if (!sql) {
      return new Response(JSON.stringify({ error: "No SQL provided" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Connect to Postgres using the internal DB URL (available in Edge Functions)
    const dbUrl = Deno.env.get("SUPABASE_DB_URL")!;
    
    const pool = new Pool(dbUrl, 1);
    const conn = await pool.connect();
    
    try {
      // Split and execute SQL statements
      const results: string[] = [];
      
      // Execute the entire migration as a single transaction
      await conn.queryArray("BEGIN");
      
      // Split SQL by semicolons, keeping only non-empty statements
      const statements = sql
        .split(";")
        .map((s: string) => s.trim())
        .filter((s: string) => s.length > 0 && !s.startsWith("--"));
      
      for (const stmt of statements) {
        try {
          await conn.queryArray(stmt);
          results.push(`✅ OK: ${stmt.substring(0, 60)}...`);
        } catch (stmtErr) {
          const errMsg = String(stmtErr);
          // Skip "already exists" errors
          if (errMsg.includes("already exists") || errMsg.includes("duplicate")) {
            results.push(`⏭️ SKIP (already exists): ${stmt.substring(0, 60)}...`);
          } else {
            throw stmtErr;
          }
        }
      }
      
      await conn.queryArray("COMMIT");
      
      return new Response(
        JSON.stringify({ 
          success: true, 
          message: "Migration completed successfully",
          results 
        }),
        { headers: { "Content-Type": "application/json" } }
      );
    } catch (err) {
      await conn.queryArray("ROLLBACK");
      return new Response(
        JSON.stringify({ 
          error: String(err),
          message: "Migration failed, transaction rolled back" 
        }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    } finally {
      conn.release();
      await pool.end();
    }
  } catch (err) {
    return new Response(JSON.stringify({ error: String(err) }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
