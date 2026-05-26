import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || 'https://svftktwdyekxzvylwvom.supabase.co';
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY || 'sb_publishable_tnGw3JvB6XtexMb6lCXpZw_aHLZLjNF';
export const supabase = createClient(supabaseUrl, supabaseKey);

export async function authenticate(loginKey, password) {
    try {
        let email = loginKey.trim();

        // Si no tiene '@', asumimos que es un username. Lo buscamos en sadimex_profiles
        if (!email.includes('@')) {
            const { data: profiles, error: profileErr } = await supabase
                .from('sadimex_profiles')
                .select('email')
                .eq('username', email)
                .limit(1);

            if (profileErr) throw profileErr;
            if (!profiles || profiles.length === 0) {
                return { success: false, error: 'Usuario no encontrado' };
            }
            email = profiles[0].email;
        }

        // Intento de login con el email determinado
        const { data, error } = await supabase.auth.signInWithPassword({
            email,
            password
        });

        if (error) {
            return { success: false, error: 'Contraseña incorrecta o cuenta inválida' };
        }

        // Cargar el perfil asociado
        const { data: profile, error: profErr } = await supabase
            .from('sadimex_profiles')
            .select('*')
            .eq('id', data.user.id)
            .single();

        if (profErr) {
            return { success: false, error: 'Error cargando el perfil del usuario' };
        }

        if (profile.activo === false) {
            await supabase.auth.signOut();
            return { success: false, error: 'Tu cuenta ha sido desactivada. Contacta al administrador.' };
        }

        return { success: true, user: { ...data.user, ...profile } };
    } catch (err) {
        console.error("Auth error:", err);
        // Mostrar el error real para poder investigarlo
        return { success: false, error: 'Error: ' + (err.message || String(err)) };
    }
}

export async function logout() {
    await supabase.auth.signOut();
}

/** Wrapper de fetch que adjunta el token automáticamente y maneja 401 → logout */
export async function apiFetch(url, options = {}) {
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) {
        await supabase.auth.signOut(); // dispara SIGNED_OUT → App.jsx redirige al login
        return null;
    }
    const res = await fetch(url, {
        ...options,
        headers: {
            Authorization: `Bearer ${session.access_token}`,
            ...(options.headers || {}),
        },
    });
    if (res.status === 401) {
        await supabase.auth.signOut();
        return null;
    }
    return res;
}

/** Resuelve username → email (para recuperar contraseña) */
export async function resolveEmail(loginKey) {
    const key = loginKey.trim();
    if (key.includes('@')) return key;
    const { data } = await supabase
        .from('sadimex_profiles')
        .select('email')
        .eq('username', key)
        .limit(1);
    return data?.[0]?.email ?? null;
}
