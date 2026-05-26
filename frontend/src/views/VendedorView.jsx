import { useState, useEffect, useMemo } from 'react';
import { supabase } from '../auth.js';

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
    return (
        <span style={{ fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 8px', borderRadius: 99, whiteSpace: 'nowrap' }}>
            {pct}% conf.
        </span>
    );
}

export default function VendedorView({ currentUser }) {
    const [visits, setVisits] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [search, setSearch] = useState('');
    const [expanded, setExpanded] = useState(null);

    useEffect(() => {
        if (!currentUser) return;
        supabase.auth.getSession().then(({ data: { session } }) => {
            fetch('/api/visits', {
                headers: { Authorization: `Bearer ${session?.access_token}` },
            })
                .then(r => r.json())
                .then(d => {
                    if (!d.ok) setError(d.error || 'Error al cargar visitas');
                    else setVisits(d.visits || []);
                })
                .catch(e => setError(e.message))
                .finally(() => setLoading(false));
        });
    }, [currentUser?.id]);

    const thisWeek = useMemo(
        () => visits.filter(v => (Date.now() - new Date(v.created_at)) / 86400000 < 7).length,
        [visits]
    );

    const filtered = useMemo(() =>
        !search
            ? visits
            : visits.filter(v =>
                (v.metadata?.cliente || '').toLowerCase().includes(search.toLowerCase())
            ),
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

            {/* Stats */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 20 }}>
                {[
                    { icon: '📋', label: 'Total', val: visits.length },
                    { icon: '📅', label: 'Esta semana', val: thisWeek },
                    { icon: '📍', label: 'Ciudad', val: CIUDAD[currentUser?.ciudad] || '—' },
                ].map(s => (
                    <div key={s.label} className="card" style={{ padding: '16px 12px', textAlign: 'center' }}>
                        <div style={{ fontSize: 22, marginBottom: 4 }}>{s.icon}</div>
                        <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-1)' }}>{s.val}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-3)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.5px', marginTop: 2 }}>{s.label}</div>
                    </div>
                ))}
            </div>

            {/* Search */}
            <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="🔍 Buscar por nombre de cliente..."
                style={{
                    width: '100%', boxSizing: 'border-box',
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    borderRadius: 'var(--r-sm)', padding: '10px 14px',
                    color: 'var(--text-1)', fontSize: 13, outline: 'none',
                    fontFamily: 'inherit', marginBottom: 14,
                }}
            />

            {/* List */}
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
                    {filtered.map(v => (
                        <div
                            key={v.id}
                            className="card"
                            style={{ padding: '15px 18px', cursor: 'pointer', transition: 'border-color 0.15s' }}
                            onClick={() => setExpanded(expanded === v.id ? null : v.id)}
                        >
                            {/* Row */}
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontWeight: 700, color: 'var(--text-1)', fontSize: 14, marginBottom: 5 }}>
                                        {v.metadata?.cliente || 'Cliente sin nombre'}
                                    </div>
                                    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 12, color: 'var(--text-3)' }}>
                                        <span>📅 {fmtDate(v.created_at)}</span>
                                        {fmtDur(v.duration_seconds) && <span>⏱ {fmtDur(v.duration_seconds)}</span>}
                                        <span>{v.source === 'microphone' ? '🎙️ Grabación' : '📁 Archivo'}</span>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
                                    <ConfBadge c={v.confidence_score} />
                                    <span style={{ fontSize: 11, color: 'var(--text-3)' }}>{expanded === v.id ? '▲' : '▼'}</span>
                                </div>
                            </div>

                            {/* Expanded transcript */}
                            {expanded === v.id && (
                                <div className="animate-in" style={{
                                    marginTop: 14, paddingTop: 14,
                                    borderTop: '1px solid var(--border)',
                                    fontSize: 13, color: 'var(--text-2)',
                                    lineHeight: 1.75, whiteSpace: 'pre-wrap',
                                    maxHeight: 280, overflowY: 'auto',
                                }}>
                                    {v.raw_text || <span style={{ color: 'var(--text-3)', fontStyle: 'italic' }}>Sin transcripción</span>}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
