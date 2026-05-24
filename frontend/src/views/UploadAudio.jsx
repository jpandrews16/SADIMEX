import { useState, useRef, useEffect, useCallback } from 'react';

const fmt = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

const STEPS = [
    { icon: "📥", label: "Validando archivo de audio" },
    { icon: "☁️", label: "Enviando a OpenAI Whisper" },
    { icon: "🎙️", label: "Transcribiendo con gpt-4o" },
    { icon: "💾", label: "Guardando en base de datos" },
];

const inputStyle = {
    width: "100%", background: "var(--bg-2)",
    border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
    padding: "9px 12px", color: "var(--text-1)", fontSize: 13,
    outline: "none", fontFamily: "inherit", transition: "border-color 0.15s",
};

function Waveform({ active }) {
    return (
        <div style={{ display: 'flex', gap: 3, alignItems: 'center', height: 36 }}>
            {Array.from({ length: 16 }).map((_, i) => (
                <div key={i} style={{
                    width: 4, borderRadius: 2,
                    background: active ? 'var(--blue)' : 'var(--bg-4)',
                    height: '20%',
                    animation: active ? `wave-${i % 4} 0.${5 + i % 4}s infinite alternate ease-in-out` : 'none',
                }} />
            ))}
        </div>
    );
}

const delay = ms => new Promise(r => setTimeout(r, ms));

export default function UploadAudio() {
    /* ── file upload state ── */
    const [file, setFile] = useState(null);
    const [drag, setDrag] = useState(false);
    const inputRef = useRef();

    /* ── recorder state ── */
    const [recState, setRecState] = useState("idle");
    const [recSeconds, setRecSeconds] = useState(0);
    const [recBlob, setRecBlob] = useState(null);
    const [recError, setRecError] = useState("");
    const [audioURL, setAudioURL] = useState("");
    const mediaRecRef = useRef(null);
    const chunksRef = useRef([]);
    const timerRef = useRef(null);
    const streamRef = useRef(null);

    /* ── form ── */
    const [form, setForm] = useState({ vendedor: "", ciudad: "LPZ", cliente: "" });
    const setField = k => e => setForm(p => ({ ...p, [k]: e.target.value }));

    /* ── pipeline state ── */
    const [currentStep, setCurrentStep] = useState(0);
    const [processing, setProcessing] = useState(false);
    const [done, setDone] = useState(false);
    const [submitError, setSubmitError] = useState("");
    const [transcript, setTranscript] = useState(null);

    /* ─── recorder logic ─── */
    const startRecording = useCallback(async () => {
        setRecError("");
        setRecState("requesting");
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;

            const mr = new MediaRecorder(stream, {
                mimeType: MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "audio/ogg"
            });
            mediaRecRef.current = mr;
            chunksRef.current = [];

            mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
            mr.onstop = () => {
                const blob = new Blob(chunksRef.current, { type: mr.mimeType });
                const url = URL.createObjectURL(blob);
                const ext = mr.mimeType.includes("ogg") ? "ogg" : "webm";
                const f = new File([blob], `grabacion_${Date.now()}.${ext}`, { type: blob.type });
                setRecBlob(blob);
                setAudioURL(url);
                setFile(f);
                setRecState("stopped");
                streamRef.current?.getTracks().forEach(t => t.stop());
            };

            mr.start(200);
            setRecState("recording");
            setRecSeconds(0);
            timerRef.current = setInterval(() => setRecSeconds(s => s + 1), 1000);
        } catch (err) {
            setRecState("idle");
            setRecError(err.name === "NotAllowedError"
                ? "Permiso de micrófono denegado. Habilítalo en la configuración del navegador."
                : `Error al acceder al micrófono: ${err.message}`);
        }
    }, []);

    const stopRecording = useCallback(() => {
        clearInterval(timerRef.current);
        mediaRecRef.current?.stop();
    }, []);

    const resetRecording = useCallback(() => {
        clearInterval(timerRef.current);
        mediaRecRef.current?.stop();
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (audioURL) URL.revokeObjectURL(audioURL);
        setRecState("idle");
        setRecBlob(null);
        setAudioURL("");
        setRecSeconds(0);
        setRecError("");
        setFile(null);
    }, [audioURL]);

    useEffect(() => () => {
        clearInterval(timerRef.current);
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (audioURL) URL.revokeObjectURL(audioURL);
    }, [audioURL]);

    /* ─── submit real ─── */
    const canSubmit = file && form.cliente && form.vendedor && !processing;

    const submit = async () => {
        if (!canSubmit) return;
        setProcessing(true);
        setDone(false);
        setSubmitError("");
        setCurrentStep(1);

        try {
            await delay(350);
            setCurrentStep(2);

            const fd = new FormData();
            fd.append("audio", file, file.name);
            fd.append("source", recBlob ? "microphone" : "file");
            fd.append("vendedor", form.vendedor);
            fd.append("ciudad", form.ciudad);
            fd.append("cliente", form.cliente);

            setCurrentStep(3);

            const res = await fetch('/api/transcribe-audio', {
                method: "POST",
                body: fd,
            });

            setCurrentStep(4);
            const data = await res.json();

            if (!res.ok || !data.ok) throw new Error(data.error || "Error desconocido en la transcripción");

            await delay(300);
            setTranscript(data);
            setDone(true);
        } catch (err) {
            setSubmitError(err.message);
        } finally {
            setProcessing(false);
        }
    };

    const reset = () => {
        setDone(false);
        setFile(null);
        setCurrentStep(0);
        setRecBlob(null);
        setAudioURL("");
        setRecState("idle");
        setRecSeconds(0);
        setTranscript(null);
        setSubmitError("");
    };

    /* ───────────── RENDER ───────────── */
    return (
        <div className="animate-in">
            <div className="page-header">
                <h2>Subir Grabación de Visita</h2>
                <p>Graba directamente con tu micrófono o sube un archivo MP3/WAV</p>
            </div>

            {!done ? (
                <div className="grid-2" style={{ alignItems: 'start' }}>

                    {/* ── LEFT COLUMN ── */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

                        {/* ── RECORD SECTION ── */}
                        <div className="card">
                            <div className="section-title">🎙️ Grabar con Micrófono</div>

                            {recError && (
                                <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '10px 14px', fontSize: 12.5, color: 'var(--red)', marginBottom: 12 }}>
                                    ⚠️ {recError}
                                </div>
                            )}

                            <div style={{
                                background: recState === "recording" ? 'var(--blue-50)' : 'var(--bg-2)',
                                border: `1.5px solid ${recState === "recording" ? 'var(--blue)' : 'var(--border)'}`,
                                borderRadius: 'var(--r)',
                                padding: '16px 18px',
                                display: 'flex', alignItems: 'center', gap: 16, marginBottom: 14,
                                transition: 'all 0.3s',
                            }}>
                                <div style={{
                                    width: 52, height: 52, borderRadius: '50%', flexShrink: 0,
                                    background: recState === "recording" ? 'var(--blue)' : 'var(--bg-3)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    fontSize: 22, cursor: recState !== "requesting" ? 'pointer' : 'default',
                                    transition: 'all 0.3s',
                                    boxShadow: recState === "recording" ? '0 0 0 5px rgba(43,94,168,0.15)' : 'none',
                                }}
                                    onClick={recState === "idle" ? startRecording : recState === "recording" ? stopRecording : undefined}
                                >
                                    {recState === "idle" && "🎙️"}
                                    {recState === "requesting" && <div style={{ width: 20, height: 20, border: '2.5px solid var(--blue)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />}
                                    {recState === "recording" && "⏹️"}
                                    {recState === "stopped" && "✅"}
                                </div>

                                <div style={{ flex: 1 }}>
                                    {recState === "idle" && <div style={{ fontWeight: 700, color: 'var(--text-1)', fontSize: 14 }}>Presiona para grabar</div>}
                                    {recState === "requesting" && <div style={{ fontWeight: 700, color: 'var(--blue)', fontSize: 14 }}>Solicitando permiso…</div>}
                                    {recState === "recording" && (
                                        <>
                                            <div style={{ fontWeight: 700, color: 'var(--blue)', fontSize: 14 }} className="pulse">● Grabando — {fmt(recSeconds)}</div>
                                            <Waveform active={true} />
                                        </>
                                    )}
                                    {recState === "stopped" && (
                                        <>
                                            <div style={{ fontWeight: 700, color: 'var(--green)', fontSize: 14 }}>✅ Grabación lista — {fmt(recSeconds)}</div>
                                            <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3 }}>Reproductor ↓ · tamaño {(file?.size / 1024).toFixed(0)} KB</div>
                                        </>
                                    )}
                                    {recState === "idle" && <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3 }}>El audio no sale del navegador hasta que lo envíes</div>}
                                </div>

                                {recState === "stopped" && (
                                    <button className="btn btn-ghost" style={{ fontSize: 12 }} onClick={resetRecording}>🔄 Volver a grabar</button>
                                )}
                            </div>

                            {recState === "idle" && (
                                <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={startRecording}>
                                    🎙️ Iniciar Grabación
                                </button>
                            )}
                            {recState === "recording" && (
                                <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center', borderColor: 'var(--red)', color: 'var(--red)' }} onClick={stopRecording}>
                                    ⏹ Detener Grabación
                                </button>
                            )}

                            {audioURL && (
                                <div style={{ marginTop: 14 }}>
                                    <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 7 }}>Reproducir antes de enviar</div>
                                    <audio controls src={audioURL} style={{ width: '100%', borderRadius: 'var(--r-sm)' }} />
                                </div>
                            )}
                        </div>

                        {/* ── OR file upload ── */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                            <span style={{ fontSize: 12, color: 'var(--text-3)', fontWeight: 600 }}>O SUBE UN ARCHIVO</span>
                            <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                        </div>

                        <div
                            className={`upload-zone ${drag ? "drag-over" : ""}`}
                            style={{ padding: '28px 24px' }}
                            onDragOver={e => { e.preventDefault(); setDrag(true); }}
                            onDragLeave={() => setDrag(false)}
                            onDrop={e => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) { setFile(f); resetRecording(); } }}
                            onClick={() => inputRef.current.click()}
                        >
                            <input ref={inputRef} type="file" accept=".mp3,.wav,.m4a,.ogg,.webm" style={{ display: 'none' }}
                                onChange={e => { const f = e.target.files[0]; if (f) { setFile(f); resetRecording(); } }} />
                            {file && !recBlob ? (
                                <>
                                    <div className="upload-icon" style={{ fontSize: 28 }}>✅</div>
                                    <h3 style={{ color: 'var(--blue)', fontSize: 14 }}>{file.name}</h3>
                                    <p style={{ fontSize: 12 }}>{(file.size / 1024).toFixed(1)} KB · listo</p>
                                </>
                            ) : (
                                <>
                                    <div className="upload-icon" style={{ fontSize: 28 }}>📁</div>
                                    <h3 style={{ fontSize: 14 }}>Arrastra MP3 / WAV aquí</h3>
                                    <p style={{ fontSize: 12 }}>máx. 200 MB</p>
                                </>
                            )}
                        </div>

                        {/* ── Metadata form ── */}
                        <div className="card">
                            <div className="section-title">📝 Datos de la Visita</div>
                            {[
                                { key: "vendedor", label: "Tu nombre", placeholder: "Ej: Juan Mamani" },
                                { key: "ciudad", label: "Ciudad", placeholder: "LPZ / CBBA / SCZ" },
                                { key: "cliente", label: "Nombre del cliente", placeholder: "Tienda Don Pepe…" },
                            ].map(f => (
                                <div key={f.key} style={{ marginBottom: 12 }}>
                                    <label style={{ display: 'block', fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 5 }}>
                                        {f.label}
                                    </label>
                                    <input
                                        value={form[f.key]}
                                        onChange={setField(f.key)}
                                        placeholder={f.placeholder}
                                        style={inputStyle}
                                        onFocus={e => e.target.style.borderColor = 'var(--blue)'}
                                        onBlur={e => e.target.style.borderColor = 'var(--border)'}
                                    />
                                </div>
                            ))}
                        </div>

                        {submitError && (
                            <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '12px 16px', fontSize: 13, color: 'var(--red)' }}>
                                ❌ {submitError}
                            </div>
                        )}

                        <button
                            className="btn btn-primary"
                            style={{ width: '100%', justifyContent: 'center', opacity: canSubmit ? 1 : 0.5, fontSize: 14, padding: '11px 0' }}
                            disabled={!canSubmit}
                            onClick={submit}
                        >
                            {processing ? "⚙️ Transcribiendo con OpenAI…" : "🚀 Enviar y Transcribir"}
                        </button>
                    </div>

                    {/* ── RIGHT COLUMN: pipeline steps ── */}
                    <div>
                        <div className="section-title">⚡ Pipeline en Tiempo Real</div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                            {STEPS.map((step, idx) => {
                                const n = idx + 1;
                                const isDone = currentStep > n;
                                const isActive = currentStep === n && processing;
                                return (
                                    <div key={n} className="card" style={{
                                        padding: '14px 18px',
                                        borderColor: isDone ? '#bbf7d0' : isActive ? 'var(--blue)' : 'var(--border)',
                                        background: isDone ? '#f0fdf4' : isActive ? 'var(--blue-50)' : 'var(--bg)',
                                        transition: 'all 0.3s',
                                        boxShadow: isActive ? 'var(--shadow-blue)' : 'var(--shadow-sm)',
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                            <div style={{
                                                width: 38, height: 38, borderRadius: '50%', flexShrink: 0,
                                                background: isDone ? '#dcfce7' : isActive ? 'var(--blue-100)' : 'var(--bg-3)',
                                                border: `1.5px solid ${isDone ? '#86efac' : isActive ? 'var(--blue)' : 'var(--border)'}`,
                                                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 16, transition: 'all 0.3s',
                                            }}>
                                                {isDone ? "✅" : step.icon}
                                            </div>
                                            <div style={{ flex: 1 }}>
                                                <div style={{ fontSize: 13, fontWeight: 700, color: isDone ? '#16a34a' : isActive ? 'var(--blue)' : 'var(--text-2)' }}>
                                                    {step.label}
                                                </div>
                                                <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 2 }}>
                                                    {isDone ? "Completado" : isActive ? <span className="pulse">Procesando…</span> : `Paso ${n} de 4`}
                                                </div>
                                            </div>
                                            {isActive && <div style={{ width: 18, height: 18, border: '2px solid var(--blue)', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>

                        <div className="card mt-16" style={{ background: 'var(--blue-50)', borderColor: 'var(--blue-100)' }}>
                            <div style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.65 }}>
                                <strong style={{ color: 'var(--blue)' }}>Privacidad</strong><br /><br />
                                El audio se envía únicamente al servidor Sadimex y a la API de OpenAI para su transcripción. Ningún tercero tiene acceso.
                            </div>
                        </div>

                        <div className="card mt-16">
                            <div style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.65 }}>
                                <strong style={{ color: 'var(--text-1)' }}>Formatos soportados</strong><br />
                                <span style={{ color: 'var(--text-3)' }}>WebM · MP3 · WAV · M4A · OGG · max 200 MB</span>
                            </div>
                        </div>
                    </div>
                </div>
            ) : (
                /* ── SUCCESS: mostrar transcripción real ── */
                <div className="animate-in">
                    <div className="card" style={{ textAlign: 'center', padding: '40px 36px 32px', borderColor: '#86efac', background: '#f0fdf4', marginBottom: 20 }}>
                        <div style={{ fontSize: 44, marginBottom: 12 }}>✅</div>
                        <h3 style={{ fontSize: 20, fontWeight: 800, color: '#15803d', marginBottom: 6 }}>¡Transcripción Completada!</h3>
                        <p style={{ color: 'var(--text-2)', marginBottom: 6 }}>
                            Visita a <strong style={{ color: 'var(--text-1)' }}>{form.cliente}</strong> guardada en base de datos.
                        </p>
                        {transcript?.duration_seconds && (
                            <div style={{ display: 'flex', gap: 16, justifyContent: 'center', marginTop: 14, flexWrap: 'wrap' }}>
                                <span className="pill pill-green">⏱ {fmt(Math.round(transcript.duration_seconds))}</span>
                                <span className="pill pill-green">🌐 {transcript.language?.toUpperCase() || 'ES'}</span>
                                {transcript.confidence_score != null && (
                                    <span className="pill pill-green">
                                        📊 Confianza {Math.round(transcript.confidence_score * 100)}%
                                    </span>
                                )}
                            </div>
                        )}
                    </div>

                    {transcript?.raw_text && (
                        <div className="card" style={{ marginBottom: 20 }}>
                            <div className="section-title">🎙️ Transcripción</div>
                            <div style={{
                                background: 'var(--bg-2)', borderRadius: 'var(--r-sm)',
                                padding: '16px 18px', fontSize: 14, color: 'var(--text-1)',
                                lineHeight: 1.75, whiteSpace: 'pre-wrap', maxHeight: 400,
                                overflowY: 'auto', border: '1px solid var(--border)',
                            }}>
                                {transcript.raw_text}
                            </div>
                        </div>
                    )}

                    <div style={{ display: 'flex', gap: 10 }}>
                        <button className="btn btn-primary" onClick={reset}>🎙️ Nueva grabación</button>
                        <button
                            className="btn btn-ghost"
                            onClick={() => navigator.clipboard?.writeText(transcript?.raw_text || '')}
                        >
                            📋 Copiar texto
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}
