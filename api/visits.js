export const config = { runtime: 'edge' };

const CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

const SUPABASE_URL = 'https://svftktwdyekxzvylwvom.supabase.co';
const SUPABASE_ANON_KEY = 'sb_publishable_tnGw3JvB6XtexMb6lCXpZw_aHLZLjNF';
const env = k => process.env[k] ?? (
    k === 'SUPABASE_URL' ? SUPABASE_URL :
    k === 'SUPABASE_ANON_KEY' ? SUPABASE_ANON_KEY : ''
);

const json = (d, s = 200) => new Response(JSON.stringify(d), {
    status: s, headers: { ...CORS, 'Content-Type': 'application/json' },
});
const err = (e, s = 400) => json({ error: e }, s);

export default async function handler(req) {
    if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });

    // ── Verificar identidad del caller ────────────────────────────────
    const authHeader = req.headers.get('Authorization');
    if (!authHeader) return err('No autorizado', 401);

    const meRes = await fetch(`${env('SUPABASE_URL')}/auth/v1/user`, {
        headers: { Authorization: authHeader, apikey: env('SUPABASE_ANON_KEY') },
    });
    if (!meRes.ok) return err('Token inválido', 401);
    const me = await meRes.json();

    // ── Perfil del caller (rol + ciudad) ─────────────────────────────
    const profileRes = await fetch(
        `${env('SUPABASE_URL')}/rest/v1/sadimex_profiles?id=eq.${me.id}&select=rol,ciudad`,
        { headers: { apikey: env('SUPABASE_ANON_KEY'), Authorization: authHeader } }
    );
    const [profile] = await profileRes.json().catch(() => [null]);
    if (!profile) return err('Perfil no encontrado', 403);

    const { rol, ciudad } = profile;
    const serviceKey = env('SUPABASE_SERVICE_ROLE_KEY');
    if (!serviceKey) return err('Servidor mal configurado (falta SERVICE_ROLE_KEY)', 500);

    // ── Construir query según rol ──────────────────────────────────────
    // Usamos service role para bypassear RLS y poder ver datos de otros
    let url = `${env('SUPABASE_URL')}/rest/v1/transcriptions`
        + `?select=id,created_at,source,duration_seconds,confidence_score,raw_text,metadata,user_id`
        + `&order=created_at.desc`
        + `&limit=300`;

    if (rol === 'vendedor') {
        // Solo sus propias visitas
        url += `&user_id=eq.${me.id}`;
    } else if (rol === 'supervisor') {
        // Solo visitas de su ciudad
        url += `&metadata->>ciudad=eq.${ciudad}`;
    }
    // gerente / admin: todas

    const dbRes = await fetch(url, {
        headers: {
            apikey: serviceKey,
            Authorization: `Bearer ${serviceKey}`,
        },
    });

    if (!dbRes.ok) {
        const e = await dbRes.text();
        return err(`Error de base de datos: ${e}`, 500);
    }

    const visits = await dbRes.json();
    return json({ ok: true, visits, rol, ciudad });
}
