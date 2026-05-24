export const config = { runtime: 'edge' };

const CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
};

export default async function handler(req) {
    if (req.method === 'OPTIONS') return new Response('ok', { headers: CORS });

    try {
        // ── Parse multipart ───────────────────────────────────────────
        const form     = await req.formData();
        const audio    = form.get('audio');
        const source   = form.get('source')   || 'file';
        const vendedor = form.get('vendedor')  || '';
        const ciudad   = form.get('ciudad')    || '';
        const cliente  = form.get('cliente')   || '';

        if (!audio || audio.size === 0) return err('No se recibió archivo de audio', 400);

        // ── Identificar usuario (opcional) ────────────────────────────
        let userId = null;
        const authHeader = req.headers.get('Authorization');
        if (authHeader) {
            const res = await supabaseGet(
                `${env('SUPABASE_URL')}/auth/v1/user`,
                { Authorization: authHeader, apikey: env('SUPABASE_ANON_KEY') }
            );
            if (res.ok) {
                const u = await res.json();
                userId = u?.id ?? null;
            }
        }

        // ── Llamar a OpenAI gpt-4o-transcribe ─────────────────────────
        const openaiForm = new FormData();
        const filename = audio.name || `audio_${Date.now()}.webm`;
        openaiForm.append('file', audio, filename);
        openaiForm.append('model', 'gpt-4o-transcribe');
        openaiForm.append('language', 'es');
        openaiForm.append('response_format', 'verbose_json');

        const openaiRes = await fetch('https://api.openai.com/v1/audio/transcriptions', {
            method: 'POST',
            headers: { Authorization: `Bearer ${env('OPENAI_API_KEY')}` },
            body: openaiForm,
        });

        if (!openaiRes.ok) {
            const body = await openaiRes.text();
            throw new Error(`OpenAI ${openaiRes.status}: ${body}`);
        }

        const t = await openaiRes.json();

        // ── Calcular confidence desde segmentos ───────────────────────
        let confidenceScore = null;
        const segments = t.segments ?? [];
        if (segments.length > 0 && segments[0].avg_logprob !== undefined) {
            const avg = segments.reduce((s, x) => s + (x.avg_logprob ?? -1), 0) / segments.length;
            confidenceScore = Math.min(1, Math.max(0, Math.exp(avg)));
        }

        // ── Guardar en Supabase via REST ──────────────────────────────
        const record = {
            source,
            duration_seconds: t.duration ?? null,
            raw_text:         t.text ?? '',
            language:         t.language ?? 'es',
            confidence_score: confidenceScore,
            audio_file_path:  null,
            metadata: {
                vendedor, ciudad, cliente,
                model: 'gpt-4o-transcribe',
                segments_count: segments.length,
                original_filename: filename,
            },
            user_id: userId,
        };

        const dbRes = await fetch(
            `${env('SUPABASE_URL')}/rest/v1/transcriptions`,
            {
                method: 'POST',
                headers: {
                    'Content-Type':  'application/json',
                    'apikey':        env('SUPABASE_SERVICE_ROLE_KEY'),
                    'Authorization': `Bearer ${env('SUPABASE_SERVICE_ROLE_KEY')}`,
                    'Prefer':        'return=representation',
                },
                body: JSON.stringify(record),
            }
        );

        if (!dbRes.ok) {
            const dbErr = await dbRes.text();
            throw new Error(`Supabase insert error: ${dbErr}`);
        }

        const [inserted] = await dbRes.json();

        return json({
            ok: true,
            id:               inserted.id,
            raw_text:         inserted.raw_text,
            duration_seconds: inserted.duration_seconds,
            language:         inserted.language,
            confidence_score: inserted.confidence_score,
        });

    } catch (e) {
        console.error('[transcribe-audio]', e);
        return err(String(e), 500);
    }
}

// ── helpers ──────────────────────────────────────────────────────────
const SUPABASE_URL_DEFAULT      = 'https://svftktwdyekxzvylwvom.supabase.co';
const env  = k => process.env[k] ?? (k === 'SUPABASE_URL' ? SUPABASE_URL_DEFAULT : '');
const json = (d, s = 200) => new Response(JSON.stringify(d), { status: s, headers: { ...CORS, 'Content-Type': 'application/json' } });
const err  = (e, s = 400) => json({ error: e }, s);
const supabaseGet = (url, headers) => fetch(url, { headers });
