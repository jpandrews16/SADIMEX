/**
 * Cliente del módulo Lector de Góndola.
 *
 * La foto se sube directo al Storage de Supabase (igual que los audios) y
 * después se registra en el servicio de góndola, que la encola. El worker
 * la procesa aparte, así que la app no espera: consulta el resultado.
 */

import { supabase } from './auth.js';

const BUCKET = 'gondola-fotos';

/** URL del servicio en Railway. Sin esto la app no puede encolar fotos. */
export const API_URL = (import.meta.env.VITE_GONDOLA_API_URL || '').replace(/\/$/, '');

export const SEMAFORO_COLOR = {
    verde:    { color: 'var(--green)',  bg: 'var(--green-bg)',  border: 'var(--green-border)',  label: 'Bien ejecutada' },
    amarillo: { color: 'var(--yellow)', bg: 'var(--yellow-bg)', border: 'var(--yellow-border)', label: 'Requiere atención' },
    rojo:     { color: 'var(--red)',    bg: 'var(--red-bg)',    border: 'var(--red-border)',    label: 'Intervención urgente' },
};

export const SEVERIDAD = {
    critico: { emoji: '🔴', label: 'Crítico', orden: 0 },
    alto:    { emoji: '🟠', label: 'Alto',    orden: 1 },
    medio:   { emoji: '🟡', label: 'Medio',   orden: 2 },
    bajo:    { emoji: '⚪', label: 'Bajo',    orden: 3 },
};

export const REGLA_LABEL = {
    presencia:   'Presencia en góndola',
    nivel:       'Altura del producto',
    frentes:     'Frentes y espacio',
    bloque:      'Bloque de marca',
    etiqueta:    'Etiqueta de precio',
    sin_quiebre: 'Góndola sin quiebres',
};

/* ── Utilidades ─────────────────────────────────────────────────── */

/**
 * Hash del archivo, para detectar una foto reciclada.
 * El backend lo recalcula: esto solo permite avisar antes de subir.
 */
export async function hashArchivo(file) {
    const buffer = await file.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', buffer);
    return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Ubicación del dispositivo. Nunca lanza: si el reponedor niega el
 * permiso la foto se sube igual y queda marcada como "sin geolocalización".
 */
export function obtenerUbicacion(timeoutMs = 8000) {
    return new Promise(resolve => {
        if (!navigator.geolocation) return resolve(null);
        navigator.geolocation.getCurrentPosition(
            pos => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, precision: pos.coords.accuracy }),
            () => resolve(null),
            { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 30000 },
        );
    });
}

async function authHeaders() {
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {};
}

async function apiFetch(ruta, opciones = {}) {
    if (!API_URL) {
        throw new Error('Falta configurar VITE_GONDOLA_API_URL con la URL del servicio de góndola.');
    }
    const resp = await fetch(`${API_URL}${ruta}`, {
        ...opciones,
        headers: {
            'Content-Type': 'application/json',
            ...(await authHeaders()),
            ...(opciones.headers || {}),
        },
    });
    const texto = await resp.text();
    let datos;
    try { datos = texto ? JSON.parse(texto) : {}; } catch { datos = { detail: texto }; }
    if (!resp.ok) throw new Error(datos.detail || `Error ${resp.status}`);
    return datos;
}

/* ── Catálogo y salas ───────────────────────────────────────────── */

export async function traerSalas(ciudad) {
    let q = supabase
        .from('salas')
        .select('id, nombre, ciudad, direccion, cadenas(id, nombre)')
        .eq('activo', true)
        .order('nombre');
    if (ciudad && ciudad !== 'ALL') q = q.eq('ciudad', ciudad);
    const { data, error } = await q;
    if (error) throw error;
    return data || [];
}

export async function traerCategorias() {
    const { data, error } = await supabase
        .from('gondola_skus')
        .select('categoria')
        .eq('activo', true);
    if (error) throw error;
    return [...new Set((data || []).map(r => r.categoria).filter(Boolean))].sort();
}

/* ── Subida y análisis ──────────────────────────────────────────── */

/**
 * Sube la foto al Storage y la encola.
 * Devuelve { photoId, alerta } — `alerta` avisa de una captura sospechosa
 * (foto repetida, sin GPS) sin bloquear el análisis.
 */
export async function subirFoto({ file, reponedorId, salaId, categoria, ubicacion, sha256 }) {
    const extension = (file.name.split('.').pop() || 'jpg').toLowerCase();
    const storagePath = `${reponedorId}/${Date.now()}.${extension}`;

    const { error: errorSubida } = await supabase.storage
        .from(BUCKET)
        .upload(storagePath, file, { contentType: file.type || 'image/jpeg', upsert: false });
    if (errorSubida) throw new Error(`No se pudo subir la foto: ${errorSubida.message}`);

    const respuesta = await apiFetch('/api/gondola/fotos', {
        method: 'POST',
        body: JSON.stringify({
            reponedor_id: reponedorId,
            sala_id: salaId,
            categoria,
            storage_path: storagePath,
            tomada_at: new Date().toISOString(),
            gps_lat: ubicacion?.lat ?? null,
            gps_lng: ubicacion?.lng ?? null,
            imagen_sha256: sha256 ?? null,
        }),
    });

    // Se pide el análisis inmediato para que el reponedor vea el resultado
    // sin esperar el turno del worker.
    try {
        await apiFetch(`/api/gondola/fotos/${respuesta.photo_id}/analizar`, { method: 'POST' });
    } catch {
        // El worker la tomará de la cola de todos modos.
    }

    return { photoId: respuesta.photo_id, alerta: respuesta.alerta_captura };
}

export async function traerAnalisis(photoId) {
    return apiFetch(`/api/gondola/analisis/${photoId}`);
}

/**
 * Consulta el resultado hasta que esté listo.
 * `onEstado` recibe cada cambio, para poder mostrar "procesando...".
 */
export async function esperarAnalisis(photoId, { intentos = 40, esperaMs = 3000, onEstado } = {}) {
    for (let i = 0; i < intentos; i++) {
        const resultado = await traerAnalisis(photoId);
        if (resultado.score !== undefined) return resultado;
        if (resultado.estado === 'error') {
            throw new Error(resultado.error || 'El análisis falló.');
        }
        onEstado?.(resultado.estado || 'procesando');
        await new Promise(r => setTimeout(r, esperaMs));
    }
    throw new Error('El análisis está tardando más de lo normal. Revisa tu historial en unos minutos.');
}

/* ── Historial y reportes ───────────────────────────────────────── */

export async function traerHistorial({ reponedorId, ciudad, limite = 40 } = {}) {
    let q = supabase
        .from('gondola_analyses')
        .select('id, photo_id, reponedor_id, ciudad, score, semaforo, share_of_shelf_pct, quiebres_detectados, hallazgos, confianza_global, calidad_foto, created_at, salas(nombre, cadenas(nombre))')
        .order('created_at', { ascending: false })
        .limit(limite);
    if (reponedorId) q = q.eq('reponedor_id', reponedorId);
    if (ciudad && ciudad !== 'ALL') q = q.eq('ciudad', ciudad);
    const { data, error } = await q;
    if (error) throw error;
    return data || [];
}

export async function traerRanking(ciudad) {
    let q = supabase.from('gondola_ranking_reponedores').select('*');
    if (ciudad && ciudad !== 'ALL') q = q.eq('ciudad', ciudad);
    const { data, error } = await q;
    if (error) throw error;
    return (data || []).sort((a, b) => (b.score_promedio || 0) - (a.score_promedio || 0));
}

export async function traerSaludSalas(ciudad) {
    let q = supabase.from('gondola_salud_salas').select('*');
    if (ciudad && ciudad !== 'ALL') q = q.eq('ciudad', ciudad);
    const { data, error } = await q;
    if (error) throw error;
    return data || [];
}

/** Nombres de los reponedores, para no mostrar UUIDs en el ranking. */
export async function traerNombres(ids) {
    if (!ids?.length) return {};
    const { data, error } = await supabase
        .from('sadimex_profiles')
        .select('id, nombre')
        .in('id', [...new Set(ids)]);
    if (error) return {};
    return Object.fromEntries((data || []).map(p => [p.id, p.nombre]));
}

/** Junta los hallazgos de varios análisis, lo urgente primero. */
export function hallazgosPrioritarios(analisis, limite = 12) {
    const todos = [];
    for (const a of analisis) {
        for (const h of a.hallazgos || []) {
            todos.push({ ...h, sala: a.salas?.nombre, cadena: a.salas?.cadenas?.nombre, fecha: a.created_at });
        }
    }
    todos.sort((x, y) => (SEVERIDAD[x.severidad]?.orden ?? 9) - (SEVERIDAD[y.severidad]?.orden ?? 9));
    return todos.slice(0, limite);
}
