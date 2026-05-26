import { useState, useEffect, useMemo } from 'react';
import { apiFetch } from '../auth.js';
import { AnalysisDetail, AnalysisPills } from '../components/AnalysisCard.jsx';

const CIUDAD = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz', NACIONAL: 'Nacional' };

const fmtDate = d => {
    const diff = (Date.now() - new Date(d)) / 1000;
    if (diff < 3600) return `hace ${Math.round(diff / 60)} min`;
    if (diff < 86400) return `hace ${Math.round(diff / 3600)} h`;
    if (diff < 172800) return 'ayer';
    return new Date(d).toLocaleDateString('es-BO', { day: '2-digit', month: 'short', year: 'numeric' });
};
const fmtDur = s => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : null;

function ConfBadge({ c }) {
    if (c == null) return null;
    const pct = Math.round(c * 100);
    const [color, bg] = c >= 0.85 ? ['#16a34a', '#dcfce7'] : c >= 0.65 ? ['#b45309', '#fef3c7'] : ['#dc2626', '#fee2e2'];
    return <span style={{ fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 8px', borderRadius: 99 }}>{pct}%</span>;
}

export default function VendedorView({ currentUser }) {
    const [visits, setVisits] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError]   = useState('');
    const [search, setSearch] = useState('');
    const [expanded, setExpanded] = useState(null);

    useEffect(() => {
        if (!currentUser) return;
        apiFetch('/api/visits')
            .then(r => r?.json())
            .then(d => { if (d && !d.ok) setError(d.error || 'Error'); else if (d) setVisits(d.visits || []); })
            .catch(e => setError(e.message))
            .finally(() => setLoading(false));
    }, [currentUser?.id]);

    // ── Métricas ──────────────────────────────────────────────────────
    const todayStr = new Date().toDateString();
    const todayCount = useMemo(
        () => visits.filter(v => new Date(v.created_at).toDateString() === todayStr).length,
        [visits]
    );
    const thisWeek = useMemo(
        () => visits.filter(v => (Date.now() - new Date(v.created_at)) / 86400000 < 7).length,
        [visits]
    );
    const meta    = currentUser?.meta_diaria || 15;
    const metaPct = Math.min(100, Math.round((todayCount / meta) * 100));

    const filtered = useMemo(() =>
        !search ? visits
            : visits.filter(v => (v.metadata?.cliente || '').toLowerCase().includes(search.toLowerCase())),
        [visits, search]
    );

    if (loading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '40vh', color: 'var(--text-3)', fontSize: 13 }}>
            Cargando visitas...
        </div>
    );

    return (
        <div className="animate-in" style={{ maxWidth: 680, margin: '0 auto' }}>
            <div className="page-header">
                <h2>Mis Visitas</h2>
                <p>{currentUser?.nombre} · {CIUDAD[currentUser?.ciudad] || currentUser?.ciudad}</p>
            </div>

            {error && (
                <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '12px 16px', fontSize: 13, color: 'var(--red)', marginBottom: 16 }}>
                    ⚠️ {error}
                </div>
            )}

            {/* ── Meta diaria ── */}
            <div className="card" style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 10 }}>
                    <span style={{ fontWeight: 700, fontSize: 13, color: 'var(--text-1)' }}>🎯 Meta de hoy</span>
                    <span style={{ fontWeight: 800, fontSize: 15, color: metaPct >= 100 ? '#16a34a' : 'var(--text-1)' }}>
                        {todayCount} / {meta} visitas
                    </span>
                </div>
                <div style={{ background: 'var(--bg-3)', borderRadius: 99, height: 10, overflow: 'hidden' }}>
                    <div style={{
                        height: '100%', borderRadius: 99, transition: 'width 0.5s ease',
                        background: metaPct >= 100 ? '#16a34a' : 'var(--blue)',
                        width: `${metaPct}%`,
                    }} />
                </div>
                {metaPct >= 100 && (
                    <p style={{ margin: '8px 0 0', fontSize: 12.5, fontWeight: 700, color: '#16a34a' }}>
                        🎉 ¡Meta cumplida! Excelente trabajo.
                    </p>
                )}
            </div>

            {/* ── Stats ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
                {[
                    { icon: '📋', label: 'Total', val: visits.length },
                    { icon: '📅', label: 'Esta semana', val: thisWeek },
                    { icon: '🏆', label: 'Con pedido', val: visits.filter(v => v.metadata?.analysis?.pedido_capturado).length },
                ].map(s => (
                    <div key={s.label} className="card" style={{ padding: '14px 12px', textAlign: 'center' }}>
                        <div style={{ fontSize: 20, marginBottom: 4 }}>{s.icon}</div>
                        <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-1)' }}>{s.val}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: 2 }}>{s.label}</div>
                    </div>
                ))}
            </div>

            {/* ── Búsqueda ── */}
            <input
                value={search} onChange={e => setSearch(e.target.value)}
                placeholder="🔍 Buscar por nombre de cliente..."
                style={{
                    width: '100%', boxSizing: 'border-box', marginBottom: 14,
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    borderRadius: 'var(--r-sm)', padding: '10px 14px',
                    color: 'var(--text-1)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
                }}
            />

            {/* ── Lista ── */}
            {filtered.length === 0 ? (
                <div className="card" style={{ textAlign: 'center', padding: '52px 24px' }}>
                    <div style={{ fontSize: 40, marginBottom: 12 }}>🎙️</div>
                    {visits.length === 0
                        ? <p style={{ color: 'var(--text-3)', fontSize: 13 }}>No tenés visitas registradas todavía.<br />Grabá tu primera visita con el botón de arriba.</p>
                        : <p style={{ color: 'var(--text-3)', fontSize: 13 }}>Sin resultados para "{search}"</p>
                    }
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {filtered.map(v => {
                        const a = v.metadata?.analysis;
                        const isOpen = expanded === v.id;
                        return (
                            <div key={v.id} className="card" style={{ padding: '15px 18px', cursor: 'pointer' }}
                                onClick={() => setExpanded(isOpen ? null : v.id)}>

                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 700, color: 'var(--text-1)', fontSize: 14, marginBottom: 5 }}>
                                            {v.metadata?.cliente || 'Cliente sin nombre'}
                                        </div>
                                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-3)', marginBottom: a ? 8 : 0 }}>
                                            <span>📅 {fmtDate(v.created_at)}</span>
                                            {fmtDur(v.duration_seconds) && <span>⏱ {fmtDur(v.duration_seconds)}</span>}
                                            <span>{v.source === 'microphone' ? '🎙️' : '📁'}</span>
                                        </div>
                                        {/* Pills de análisis siempre visibles */}
                                        {a && <AnalysisPills a={a} />}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                                        <ConfBadge c={v.confidence_score} />
                                        <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{isOpen ? '▲' : '▼'}</span>
                                    </div>
                                </div>

                                {/* Expandido: análisis completo + transcripción */}
                                {isOpen && (
                                    <div className="animate-in" style={{ marginTop: 14, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
                                        <div style={{ marginBottom: 14 }}>
                                            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>
                                                🧠 Análisis IA
                                            </div>
                                            <AnalysisDetail a={a} />
                                        </div>
                                        {v.raw_text && (
                                            <>
                                                <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>
                                                    🎙️ Transcripción
                                                </div>
                                                <div style={{
                                                    fontSize: 13, color: 'var(--text-2)', lineHeight: 1.75,
                                                    whiteSpace: 'pre-wrap', maxHeight: 260, overflowY: 'auto',
                                                    background: 'var(--bg-2)', borderRadius: 'var(--r-sm)',
                                                    padding: '12px 14px', border: '1px solid var(--border)',
                                                }}>
                                                    {v.raw_text}
                                                </div>
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
