import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req: Request) => {
    // CORS preflight
    if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

    // ── Auth: verify caller is an admin ──────────────────────────────
    const authHeader = req.headers.get("Authorization");
    if (!authHeader) return json({ error: "No autorizado" }, 401);

    const supabaseClient = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_ANON_KEY")!,
        { global: { headers: { Authorization: authHeader } } }
    );

    const { data: { user }, error: authErr } = await supabaseClient.auth.getUser();
    if (authErr || !user) return json({ error: "Token inválido" }, 401);

    // Check that caller has role = admin in sadimex_profiles
    const { data: callerProfile, error: profileErr } = await supabaseClient
        .from("sadimex_profiles")
        .select("rol")
        .eq("id", user.id)
        .single();

    if (profileErr || !callerProfile || callerProfile.rol !== "admin") {
        return json({ error: "Solo admins pueden crear usuarios" }, 403);
    }

    // ── Parse body ────────────────────────────────────────────────────
    const { nombre, email, password, rol, ciudad } = await req.json();
    if (!nombre || !email || !password || !rol || !ciudad) {
        return json({ error: "Todos los campos son requeridos" }, 400);
    }

    const VALID_ROLES = ["gerente", "supervisor", "vendedor", "admin"];
    const VALID_CITIES = ["LPZ", "CBBA", "SCZ", "NACIONAL"];
    if (!VALID_ROLES.includes(rol)) return json({ error: "Rol inválido" }, 400);
    if (!VALID_CITIES.includes(ciudad)) return json({ error: "Ciudad inválida" }, 400);

    // ── Admin client (service role) ───────────────────────────────────
    const supabaseAdmin = createClient(
        Deno.env.get("SUPABASE_URL")!,
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
        { auth: { autoRefreshToken: false, persistSession: false } }
    );

    // Create auth user
    const { data: newUser, error: createErr } = await supabaseAdmin.auth.admin.createUser({
        email,
        password,
        email_confirm: true,   // skip email confirmation
        user_metadata: { nombre, rol, ciudad },
    });

    if (createErr) return json({ error: createErr.message }, 400);

    // Insert profile
    const { error: insertErr } = await supabaseAdmin
        .from("sadimex_profiles")
        .insert({ id: newUser.user.id, nombre, rol, ciudad });

    if (insertErr) {
        // Rollback: delete the auth user
        await supabaseAdmin.auth.admin.deleteUser(newUser.user.id);
        return json({ error: `Error al crear perfil: ${insertErr.message}` }, 500);
    }

    return json({
        ok: true,
        user: { id: newUser.user.id, email, nombre, rol, ciudad },
    });
});

function json(data: unknown, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
}
