import { useState, useRef, useEffect, useCallback } from 'react';
import { supabase } from '../auth.js';
import { AnalysisDetail } from '../components/AnalysisCard.jsx';

const CIUDAD_LABEL = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz', NACIONAL: 'Nacional' };

const fmt = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

/* ── Autocomplete de clientes ── */
function ClienteInput({ value, onChange }) {
    const [sugs, setSugs] = useState([]);
    const [open, setOpen] = useState(false);
    const ref = useRef();

    useEffect(() => {
        const handler = e => { if (!ref.current?.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const search = async q => {
        onChange(q);
        if (q.length < 2) { setSugs([]); setOpen(false); return; }
        const { data } = await supabase.rpc
            ? supabase.from('transcriptions')
                .select('metadata')
                .ilike('metadata->>cliente', `%${q}%`)
                .limit(6)
            : { data: [] };
        if (data?.length) {
            const unique = [...new Set(data.map(r => r.metadata?.cliente).filter(Boolean))];
            setSugs(unique);
            setOpen(true);
        } else {
            setSugs([]);
            setOpen(false);
        }
    };

    return (
        <div ref={ref} style={{ position: 'relative' }}>
            <input
                value={value}
                onChange={e => search(e.target.value)}
                onFocus={() => sugs.length && setOpen(true)}
                placeholder="Ej: Tienda Don Pepe"
                style={inputSt}
                onFocus={e => { e.target.style.borderColor = 'var(--blue)'; sugs.length && setOpen(true); }}
                onBlur={e => e.target.style.borderColor = 'var(--border)'}
                autoComplete="off"
            />
            {open && sugs.length > 0 && (
                <div style={{
                    position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 100,
                    background: 'var(--bg)', border: '1px solid var(--border)',
                    borderRadius: 'var(--r-sm)', boxShadow: 'var(--shadow)',
                    overflow: 'hidden', marginTop: 2,
                }}>
                    {sugs.map((s, i) => (
                        <div key={i}
                            style={{ padding: '9px 12px', cursor: 'pointer', fontSize: 13, color: 'var(--text-1)', borderBottom: i < sugs.length - 1 ? '1px solid var(--border)' : 'none' }}
                            onMouseDown={() => { onChange(s); setOpen(false); }}
                            onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                            onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                        >
                            {s}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

const inputSt = {
    width: '100%', background: 'var(--bg-2)',
    border: '1px solid var(--border)', borderRadius: 'var(--r-sm)',
    padding: '10px 13px', color: 'var(--text-1)', fontSize: 14,
    outline: 'none', fontFamily: 'inherit', transition: 'border-color 0.15s',
    boxSizing: 'border-box',
};

/* ── Waveform animado ── */
function Waveform() {
    return (
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', height: 32, justifyContent: 'center' }}>
            {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} style={{
                    width: 4, borderRadius: 2, background: '#fff',
                    height: '30%',
                    animation: `wave-${i % 4} 0.${5 + i % 4}s infinite alternate ease-in-out`,
                }} />
            ))}
        </div>
    );
}

/* ── Barra de progreso animada ── */
function ProgressBar() {
    const [pct, setPct] = useState(5);
    useEffect(() => {
        const id = setInterval(() => setPct(p => p < 85 ? p + Math.random() * 4 : p), 600);
        return () => clearInterval(id);
    }, []);
    return (
        <div style={{ width: '100%', background: 'var(--bg-3)', borderRadius: 99, height: 8, overflow: 'hidden' }}>
            <div style={{
                height: '100%', borderRadius: 99,
                background: 'linear-gradient(90deg, var(--blue), #5a8fd4)',
                width: `${pct}%`, transition: 'width 0.6s ease',
            }} />
        </div>
    );
}

// iOS Safari no soporta MediaRecorder — detectamos y mostramos solo file input
const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);

export default function UploadAudio({ currentUser }) {
    /* ── form ── */
    const ciudad = currentUser?.ciudad || 'LPZ';
    const [cliente, setCliente] = useState('');

    /* ── recorder ── */
    const [recState, setRecState] = useState('idle'); // idle | requesting | recording | stopped
    const [recSeconds, setRecSeconds] = useState(0);
    const [recError, setRecError] = useState('');
    const [audioURL, setAudioURL] = useState('');
    const [file, setFile] = useState(null);
    const [recBlob, setRecBlob] = useState(null);
    const mediaRecRef = useRef(null);
    const chunksRef = useRef([]);
    const timerRef = useRef(null);
    const streamRef = useRef(null);
    const inputRef = useRef();

    const startRecording = useCallback(async () => {
        setRecError('');
        setRecState('requesting');
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;
            const mr = new MediaRecorder(stream, {
                mimeType: MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg',
            });
            mediaRecRef.current = mr;
            chunksRef.current = [];
            mr.ondataavailable = e => { if (e.data.size > 0) chunksRef.current.push(e.data); };
            mr.onstop = () => {
                const blob = new Blob(chunksRef.current, { type: mr.mimeType });
                const ext = mr.mimeType.includes('ogg') ? 'ogg' : 'webm';
                const f = new File([blob], `visita_${Date.now()}.${ext}`, { type: blob.type });
                setRecBlob(blob);
                setAudioURL(URL.createObjectURL(blob));
                setFile(f);
                setRecState('stopped');
                streamRef.current?.getTracks().forEach(t => t.stop());
            };
            mr.start(200);
            setRecState('recording');
            setRecSeconds(0);
            timerRef.current = setInterval(() => setRecSeconds(s => s + 1), 1000);
        } catch (err) {
            setRecState('idle');
            setRecError(err.name === 'NotAllowedError'
                ? 'Permiso de micrófono denegado. Habilítalo en la configuración del navegador.'
                : `Error al acceder al micrófono: ${err.message}`);
        }
    }, []);

    const stopRecording = useCallback(() => {
        clearInterval(timerRef.current);
        mediaRecRef.current?.stop();
    }, []);

    const resetRec = useCallback(() => {
        clearInterval(timerRef.current);
        mediaRecRef.current?.stop();
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (audioURL) URL.revokeObjectURL(audioURL);
        setRecState('idle'); setRecBlob(null); setAudioURL('');
        setRecSeconds(0); setRecError(''); setFile(null);
    }, [audioURL]);

    useEffect(() => () => {
        clearInterval(timerRef.current);
        streamRef.current?.getTracks().forEach(t => t.stop());
        if (audioURL) URL.revokeObjectURL(audioURL);
    }, [audioURL]);

    /* ── submit ── */
    const canSubmit = file && cliente.trim() && recState !== 'recording';
    const [processing, setProcessing] = useState(false);
    const [done, setDone] = useState(false);
    const [transcript, setTranscript] = useState(null);
    const [submitError, setSubmitError] = useState('');

    const submit = async () => {
        if (!canSubmit) return;
        setProcessing(true);
        setSubmitError('');
        try {
            const fd = new FormData();
            fd.append('audio', file, file.name);
            fd.append('source', recBlob ? 'microphone' : 'file');
            fd.append('vendedor', currentUser?.nombre || currentUser?.email || '');
            fd.append('ciudad', ciudad);
            fd.append('cliente', cliente.trim());

            const res = await fetch('/api/transcribe-audio', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok || !data.ok) throw new Error(data.error || 'Error en la transcripción');
            setTranscript(data);
            setDone(true);
        } catch (e) {
            setSubmitError(e.message);
        } finally {
            setProcessing(false);
        }
    };

    const reset = () => {
        setDone(false); setTranscript(null); setSubmitError('');
        setFile(null); setRecBlob(null); setAudioURL('');
        setRecState('idle'); setRecSeconds(0); setCliente('');
    };

    /* ── render ── */

    // Procesando
    if (processing) return (
        <div className="animate-in" style={{ maxWidth: 480, margin: '60px auto', textAlign: 'center', padding: '0 16px' }}>
            <div style={{ fontSize: 48, marginBottom: 20 }}>⏳</div>
            <h3 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-1)', marginBottom: 8 }}>Analizando tu visita…</h3>
            <p style={{ color: 'var(--text-3)', fontSize: 13, marginBottom: 28 }}>Esto tarda entre 10 y 30 segundos</p>
            <ProgressBar />
        </div>
    );

    // Éxito
    if (done) return (
        <div className="animate-in" style={{ maxWidth: 560, margin: '0 auto', padding: '0 16px' }}>
            <div className="card" style={{ textAlign: 'center', padding: '36px 28px 28px', borderColor: '#86efac', background: '#f0fdf4', marginBottom: 16 }}>
                <div style={{ fontSize: 44, marginBottom: 12 }}>✅</div>
                <h3 style={{ fontSize: 20, fontWeight: 800, color: '#15803d', marginBottom: 6 }}>¡Visita registrada!</h3>
                <p style={{ color: 'var(--text-2)', fontSize: 13 }}>
                    <strong>{cliente}</strong> · {CIUDAD_LABEL[ciudad] || ciudad}
                </p>
                {transcript?.duration_seconds && (
                    <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 14, flexWrap: 'wrap' }}>
                        <span className="pill pill-green">⏱ {fmt(Math.round(transcript.duration_seconds))}</span>
                        {transcript.confidence_score != null && (
                            <span className="pill pill-green">📊 {Math.round(transcript.confidence_score * 100)}% confianza</span>
                        )}
                    </div>
                )}
            </div>

            {transcript?.analysis && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="section-title">🧠 Análisis IA</div>
                    <AnalysisDetail a={transcript.analysis} />
                </div>
            )}

            {transcript?.raw_text && (
                <div className="card" style={{ marginBottom: 16 }}>
                    <div className="section-title">🎙️ Transcripción</div>
                    <div style={{
                        background: 'var(--bg-2)', borderRadius: 'var(--r-sm)', padding: '14px 16px',
                        fontSize: 13.5, color: 'var(--text-1)', lineHeight: 1.75,
                        whiteSpace: 'pre-wrap', maxHeight: 320, overflowY: 'auto',
                        border: '1px solid var(--border)',
                    }}>
                        {transcript.raw_text}
                    </div>
                </div>
            )}

            <div style={{ display: 'flex', gap: 10 }}>
                <button className="btn btn-primary" style={{ flex: 1, justifyContent: 'center' }} onClick={reset}>
                    🎙️ Nueva visita
                </button>
                <button className="btn btn-ghost" onClick={() => navigator.clipboard?.writeText(transcript?.raw_text || '')}>
                    📋 Copiar
                </button>
            </div>
        </div>
    );

    // Formulario principal
    return (
        <div className="animate-in" style={{ maxWidth: 520, margin: '0 auto', padding: '0 16px' }}>
            <div className="page-header">
                <h2>Registrar Visita</h2>
                <p>Grabá la conversación con tu cliente</p>
            </div>

            {/* ── Datos básicos ── */}
            <div className="card" style={{ marginBottom: 16 }}>

                {/* Vendedor (solo lectura) */}
                <div style={{ marginBottom: 14 }}>
                    <label style={labelSt}>Vendedor</label>
                    <div style={{ ...inputSt, color: 'var(--text-3)', background: 'var(--bg-3)', cursor: 'default' }}>
                        {currentUser?.nombre || currentUser?.email || '—'}
                    </div>
                </div>

                {/* Cliente con autocomplete */}
                <div>
                    <label style={labelSt}>Nombre del cliente</label>
                    <ClienteInput value={cliente} onChange={setCliente} />
                </div>
            </div>

            {/* ── Grabación ── */}
            <div className="card" style={{ marginBottom: 16 }}>
                {recError && (
                    <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '10px 14px', fontSize: 12.5, color: 'var(--red)', marginBottom: 14 }}>
                        ⚠️ {recError}
                    </div>
                )}

                {/* Botón grande de grabación */}
                {/* ── iOS: MediaRecorder no disponible → solo file ── */}
                {isIOS ? (
                    <div>
                        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', padding: '12px 14px', marginBottom: 12, fontSize: 12.5, color: 'var(--text-3)', lineHeight: 1.5 }}>
                            📱 En iPhone, grabá con la app <strong>Notas de Voz</strong> y después subí el archivo aquí.
                        </div>
                        {!file ? (
                            <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center', fontSize: 15, padding: '16px' }}
                                onClick={() => inputRef.current.click()}>
                                📁 Seleccionar audio
                            </button>
                        ) : (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                                <span style={{ fontSize: 13, color: 'var(--text-2)', fontWeight: 600 }}>✅ {file.name}</span>
                                <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }} onClick={resetRec}>✕</button>
                            </div>
                        )}
                        <input ref={inputRef} type="file" accept=".mp3,.wav,.m4a,.ogg,.webm,.mp4" style={{ display: 'none' }}
                            onChange={e => { const f = e.target.files[0]; if (f) { setFile(f); setRecState('stopped'); setRecSeconds(0); } }} />
                    </div>
                ) : (
                    <>
                        {recState === 'idle' && (
                            <button className="btn btn-primary"
                                style={{ width: '100%', justifyContent: 'center', fontSize: 15, padding: '16px', gap: 10 }}
                                onClick={startRecording}>
                                🎙️ Iniciar Grabación
                            </button>
                        )}

                        {recState === 'requesting' && (
                            <div style={{ textAlign: 'center', padding: '16px 0', color: 'var(--blue)', fontWeight: 600, fontSize: 14 }}>
                                Solicitando permiso de micrófono…
                            </div>
                        )}

                        {recState === 'recording' && (
                            <button style={{ width: '100%', border: 'none', borderRadius: 'var(--r)', background: 'var(--blue)', color: '#fff', padding: '16px', cursor: 'pointer', fontSize: 15, fontWeight: 700 }}
                                onClick={stopRecording}>
                                <div style={{ marginBottom: 6 }} className="pulse">⏹ Detener — {fmt(recSeconds)}</div>
                                <Waveform />
                            </button>
                        )}

                        {recState === 'stopped' && (
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                                    <span style={{ fontWeight: 700, color: 'var(--green)', fontSize: 14 }}>
                                        ✅ {recBlob ? `Grabación lista — ${fmt(recSeconds)}` : file?.name}
                                    </span>
                                    <button className="btn btn-ghost" style={{ fontSize: 12, padding: '4px 10px' }} onClick={resetRec}>
                                        🔄 Repetir
                                    </button>
                                </div>
                                {audioURL && <audio controls src={audioURL} style={{ width: '100%', borderRadius: 'var(--r-sm)' }} />}
                            </div>
                        )}

                        {recState === 'idle' && (
                            <>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '14px 0' }}>
                                    <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                                    <span style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600 }}>O SUBÍ UN ARCHIVO</span>
                                    <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />
                                </div>
                                <button className="btn btn-ghost" style={{ width: '100%', justifyContent: 'center', fontSize: 13 }}
                                    onClick={() => inputRef.current.click()}>
                                    📁 Seleccionar MP3 / WAV
                                </button>
                                <input ref={inputRef} type="file" accept=".mp3,.wav,.m4a,.ogg,.webm" style={{ display: 'none' }}
                                    onChange={e => { const f = e.target.files[0]; if (f) { setFile(f); setRecState('stopped'); setRecSeconds(0); } }} />
                            </>
                        )}
                    </>
                )}
            </div>

            {/* ── Error ── */}
            {submitError && (
                <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '12px 16px', fontSize: 13, color: 'var(--red)', marginBottom: 16 }}>
                    ❌ {submitError}
                </div>
            )}

            {/* ── Enviar ── */}
            <button
                className="btn btn-primary"
                style={{
                    width: '100%', justifyContent: 'center', fontSize: 15,
                    padding: '14px 0', opacity: canSubmit ? 1 : 0.4,
                    marginBottom: 32,
                }}
                disabled={!canSubmit}
                onClick={submit}
            >
                🚀 Enviar Visita
            </button>
        </div>
    );
}

const labelSt = {
    display: 'block', fontSize: 11, fontWeight: 700,
    color: 'var(--text-3)', textTransform: 'uppercase',
    letterSpacing: '1px', marginBottom: 6,
};
