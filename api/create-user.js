export const config = { runtime: 'edge' };

const CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

const SUPABASE_URL = 'https://svftktwdyekxzvylwvom.supabase.co';
const env = k => process.env[k] ?? (k === 'SUPABASE_URL' ? SUPABASE_URL : '');

const json = (d, s = 200) => new Response(JSON.stringify(d), {
    status: s, headers: { ...CORS, 'Content-Type': 'application/json' },
});
const err = (e, s = 400) => json({ error: e }, s);

const VALID_ROLES  = ['gerente', 'supervisor', 'vendedor', 'admin'];
const VALID_CITIES = ['LPZ', 'CBBA', 'SCZ', 'NACIONAL'];

export default async function handler(req) {
    if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });

    // ── Verificar que el caller sea admin ─────────────────────────────
    const authHeader = req.headers.get('Authorization');
    if (!authHeader) return err('No autorizado', 401);

    const meRes = await fetch(`${env('SUPABASE_URL')}/auth/v1/user`, {
        headers: { Authorization: authHeader, apikey: env('SUPABASE_ANON_KEY') },
    });
    if (!meRes.ok) return err('Token inválido', 401);

    const me = await meRes.json();
    const callerRes = await fetch(
        `${env('SUPABASE_URL')}/rest/v1/sadimex_profiles?id=eq.${me.id}&select=rol`,
        { headers: { apikey: env('SUPABASE_ANON_KEY'), Authorization: authHeader } },
    );
    const [callerProfile] = await callerRes.json();
    if (!callerProfile || callerProfile.rol !== 'admin') {
        return err('Solo admins pueden crear usuarios', 403);
    }

    // ── Parsear body ──────────────────────────────────────────────────
    const body = await req.json().catch(() => ({}));
    const { nombre, email, password, rol, ciudad, username } = body;

    if (!nombre || !email || !password || !rol || !ciudad) {
        return err('Todos los campos son requeridos (nombre, email, password, rol, ciudad)');
    }
    if (!VALID_ROLES.includes(rol))  return err('Rol inválido');
    if (!VALID_CITIES.includes(ciudad)) return err('Ciudad inválida');

    const serviceKey = env('SUPABASE_SERVICE_ROLE_KEY');
    if (!serviceKey) return err('Servidor mal configurado (falta SERVICE_ROLE_KEY)', 500);

    const adminHeaders = {
        'Content-Type': 'application/json',
        'apikey':        serviceKey,
        'Authorization': `Bearer ${serviceKey}`,
    };

    // ── Crear usuario en Supabase Auth ────────────────────────────────
    const createRes = await fetch(`${env('SUPABASE_URL')}/auth/v1/admin/users`, {
        method: 'POST',
        headers: adminHeaders,
        body: JSON.stringify({
            email,
            password,
            email_confirm: true,
            user_metadata: { nombre, rol, ciudad },
        }),
    });

    if (!createRes.ok) {
        const e = await createRes.json();
        return err(e.msg || e.message || 'Error al crear usuario en Auth', 400);
    }

    const newUser = await createRes.json();
    const userId = newUser.id;

    // ── Insertar perfil en sadimex_profiles ───────────────────────────
    const un = username || email.split('@')[0];
    const profileRes = await fetch(`${env('SUPABASE_URL')}/rest/v1/sadimex_profiles`, {
        method: 'POST',
        headers: { ...adminHeaders, 'Prefer': 'return=representation' },
        body: JSON.stringify({ id: userId, nombre, email, rol, ciudad, username: un, activo: true }),
    });

    if (!profileRes.ok) {
        const pErr = await profileRes.text();
        // Rollback: eliminar el usuario de Auth
        await fetch(`${env('SUPABASE_URL')}/auth/v1/admin/users/${userId}`, {
            method: 'DELETE', headers: adminHeaders,
        });
        return err(`Error al crear perfil: ${pErr}`, 500);
    }

    const [profile] = await profileRes.json();

    return json({
        ok: true,
        user: { id: userId, email, nombre, rol, ciudad, username: un },
    });
}
