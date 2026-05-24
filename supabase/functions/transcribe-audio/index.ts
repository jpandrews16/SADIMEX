import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

const corsHeaders = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req: Request) => {
    if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

    try {
        // ── Parse multipart form ─────────────────────────────────────────
        const formData = await req.formData();
        const audioFile = formData.get("audio") as File | null;
        const source    = (formData.get("source") as string) || "file";
        const vendedor  = (formData.get("vendedor") as string) || "";
        const ciudad    = (formData.get("ciudad")   as string) || "";
        const cliente   = (formData.get("cliente")  as string) || "";

        if (!audioFile || audioFile.size === 0) {
            return json({ error: "No se recibió archivo de audio" }, 400);
        }

        // ── Identificar usuario (opcional) ───────────────────────────────
        let userId: string | null = null;
        const authHeader = req.headers.get("Authorization");
        if (authHeader) {
            const supabaseUser = createClient(
                Deno.env.get("SUPABASE_URL")!,
                Deno.env.get("SUPABASE_ANON_KEY")!,
                { global: { headers: { Authorization: authHeader } } }
            );
            const { data: { user } } = await supabaseUser.auth.getUser();
            userId = user?.id ?? null;
        }

        // ── Llamar a OpenAI gpt-4o-transcribe ────────────────────────────
        const openaiKey = Deno.env.get("OPENAI_API_KEY");
        if (!openaiKey) throw new Error("OPENAI_API_KEY no configurada en secrets");

        const openaiForm = new FormData();
        // Aseguramos extensión correcta para que OpenAI detecte el formato
        const filename = audioFile.name || `audio_${Date.now()}.webm`;
        openaiForm.append("file", audioFile, filename);
        openaiForm.append("model", "gpt-4o-transcribe");
        openaiForm.append("language", "es");
        openaiForm.append("response_format", "verbose_json");

        const openaiRes = await fetch("https://api.openai.com/v1/audio/transcriptions", {
            method: "POST",
            headers: { Authorization: `Bearer ${openaiKey}` },
            body: openaiForm,
        });

        if (!openaiRes.ok) {
            const errBody = await openaiRes.text();
            throw new Error(`OpenAI error ${openaiRes.status}: ${errBody}`);
        }

        const transcription = await openaiRes.json();

        // ── Calcular confidence promedio desde segmentos ─────────────────
        let confidenceScore: number | null = null;
        const segments: Array<{ avg_logprob?: number }> = transcription.segments ?? [];
        if (segments.length > 0 && segments[0].avg_logprob !== undefined) {
            const avgLogprob = segments.reduce(
                (sum, seg) => sum + (seg.avg_logprob ?? -1), 0
            ) / segments.length;
            // Convertir log-prob a probabilidad [0, 1]
            confidenceScore = Math.min(1, Math.max(0, Math.exp(avgLogprob)));
        }

        // ── Persistir en Supabase ────────────────────────────────────────
        const supabaseAdmin = createClient(
            Deno.env.get("SUPABASE_URL")!,
            Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
            { auth: { autoRefreshToken: false, persistSession: false } }
        );

        const record = {
            source,
            duration_seconds: transcription.duration ?? null,
            raw_text: transcription.text ?? "",
            language: transcription.language ?? "es",
            confidence_score: confidenceScore,
            audio_file_path: null,
            metadata: {
                vendedor,
                ciudad,
                cliente,
                model: "gpt-4o-transcribe",
                segments_count: segments.length,
                original_filename: filename,
            },
            user_id: userId,
        };

        const { data: inserted, error: insertErr } = await supabaseAdmin
            .from("transcriptions")
            .insert(record)
            .select()
            .single();

        if (insertErr) throw new Error(`Error al guardar en DB: ${insertErr.message}`);

        return json({
            ok: true,
            id: inserted.id,
            raw_text: inserted.raw_text,
            duration_seconds: inserted.duration_seconds,
            language: inserted.language,
            confidence_score: inserted.confidence_score,
        });

    } catch (err) {
        console.error("[transcribe-audio]", err);
        return json({ error: String(err) }, 500);
    }
});

function json(data: unknown, status = 200) {
    return new Response(JSON.stringify(data), {
        status,
        headers: { ...corsHeaders, "Content-Type": "application/json" },
    });
}
