import { useState, useEffect, useMemo } from 'react';
import { supabase } from '../auth.js';

const CIUDAD = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz', NACIONAL: 'Nacional' };

const fmtDate = d => {
    const diff = (Date.now() - new Date(d)) / 1000;
    if (diff < 3600) return `hace ${Math.round(diff / 60)} min`;
    if (diff < 86400) return `hace ${Math.round(diff / 3600)} h`;
    if (diff < 172800) return 'ayer';
    return new Date(d).toLocaleDateString('es-BO', { day: '2-digit', month: 'short' });
};
const fmtDur = s => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : '—';

function ConfBadge({ c }) {
    if (c == null) return <span style={{ color: 'var(--text-3)', fontSize: 12 }}>—</span>;
    const pct = Math.round(c * 100);
    const [color, bg] = c >= 0.85 ? ['#16a34a', '#dcfce7'] : c >= 0.65 ? ['#b45309', '#fef3c7'] : ['#dc2626', '#fee2e2'];
    return <span style={{ fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 7px', borderRadius: 99 }}>{pct}%</span>;
}

export default function SupervisorView({ currentUser }) {
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
                    if (!d.ok) setError(d.error || 'Error al cargar');
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

    // Agrupar por vendedor
    const byVendedor = useMemo(() => {
        const map = {};
        visits.forEach(v => {
            const name = v.metadata?.vendedor || 'Sin nombre';
            if (!map[name]) map[name] = { name, count: 0, last: null };
            map[name].count++;
            if (!map[name].last || v.created_at > map[name].last) map[name].last = v.created_at;
        });
        return Object.values(map).sort((a, b) => b.count - a.count);
    }, [visits]);

    const avgDur = useMemo(() => {
        const withDur = visits.filter(v => v.duration_seconds);
        if (!withDur.length) return null;
        return withDur.reduce((a, v) => a + v.duration_seconds, 0) / withDur.length;
    }, [visits]);

    const filtered = useMemo(() =>
        visits.filter(v =>
            !search ||
            (v.metadata?.cliente || '').toLowerCase().includes(search.toLowerCase()) ||
            (v.metadata?.vendedor || '').toLowerCase().includes(search.toLowerCase())
        ),
        [visits, search]
    );

    if (loading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '40vh', color: 'var(--text-3)', fontSize: 13 }}>
            Cargando equipo...
        </div>
    );

    const cityName = CIUDAD[currentUser?.ciudad] || currentUser?.ciudad || '';

    return (
        <div className="animate-in">
            <div className="page-header">
                <div className="flex-between">
                    <div>
                        <h2>Mi Equipo — {cityName}</h2>
                        <p>{byVendedor.length} vendedores · {visits.length} visitas registradas</p>
                    </div>
                    <span className="pill pill-green">● En vivo</span>
                </div>
            </div>

            {error && (
                <div style={{ background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r-sm)', padding: '12px 16px', fontSize: 13, color: 'var(--red)', marginBottom: 16 }}>
                    ⚠️ {error}
                </div>
            )}

            {/* KPIs */}
            <div className="kpi-grid" style={{ marginBottom: 24 }}>
                {[
                    { icon: '📋', label: 'Total visitas', val: visits.length, cls: 'blue' },
                    { icon: '📅', label: 'Esta semana', val: thisWeek, cls: 'green' },
                    { icon: '🧑‍💼', label: 'Vendedores', val: byVendedor.length, cls: 'yellow' },
                    { icon: '⏱', label: 'Prom. duración', val: avgDur ? fmtDur(avgDur) : '—', cls: 'blue' },
                ].map(s => (
                    <div key={s.label} className={`kpi-card ${s.cls}`}>
                        <div className="kpi-icon">{s.icon}</div>
                        <div className="kpi-label">{s.label}</div>
                        <div className="kpi-value">{s.val}</div>
                    </div>
                ))}
            </div>

            {/* Cards por vendedor */}
            {byVendedor.length > 0 && (
                <>
                    <div className="section-title">🧑‍💼 Actividad por Vendedor</div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: 12, marginBottom: 28 }}>
                        {byVendedor.map(v => (
                            <div key={v.name} className="card" style={{ padding: '16px 18px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-1)', marginBottom: 3 }}>{v.name}</div>
                                    <div style={{ fontSize: 12, color: 'var(--text-3)' }}>Última: {fmtDate(v.last)}</div>
                                </div>
                                <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                                    <div style={{ fontSize: 28, fontWeight: 800, color: 'var(--blue)', lineHeight: 1 }}>{v.count}</div>
                                    <div style={{ fontSize: 11, color: 'var(--text-3)' }}>visitas</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </>
            )}

            {/* Tabla de visitas */}
            <div className="section-title">🗒️ Visitas Recientes</div>
            <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="🔍 Buscar por cliente o vendedor..."
                style={{
                    width: '100%', boxSizing: 'border-box', marginBottom: 12,
                    background: 'var(--bg-2)', border: '1px solid var(--border)',
                    borderRadius: 'var(--r-sm)', padding: '10px 14px',
                    color: 'var(--text-1)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
                }}
            />

            {filtered.length === 0 ? (
                <div className="card" style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-3)' }}>
                    <div style={{ fontSize: 36, marginBottom: 12 }}>🕵️</div>
                    <p>{visits.length === 0 ? 'No hay visitas registradas en tu ciudad todavía.' : `Sin resultados para "${search}"`}</p>
                </div>
            ) : (
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Fecha</th>
                                <th>Vendedor</th>
                                <th>Cliente</th>
                                <th>Duración</th>
                                <th>Confianza</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.flatMap(v => {
                                const rows = [
                                    <tr key={v.id} style={{ cursor: 'pointer' }}
                                        onClick={() => setExpanded(expanded === v.id ? null : v.id)}>
                                        <td style={{ fontSize: 12, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{fmtDate(v.created_at)}</td>
                                        <td><strong style={{ fontSize: 13 }}>{v.metadata?.vendedor || '—'}</strong></td>
                                        <td style={{ fontSize: 13 }}>{v.metadata?.cliente || '—'}</td>
                                        <td style={{ fontSize: 12, color: 'var(--text-3)' }}>{fmtDur(v.duration_seconds)}</td>
                                        <td><ConfBadge c={v.confidence_score} /></td>
                                        <td style={{ color: 'var(--text-3)', fontSize: 11 }}>{expanded === v.id ? '▲' : '▼'}</td>
                                    </tr>
                                ];
                                if (expanded === v.id && v.raw_text) {
                                    rows.push(
                                        <tr key={`${v.id}-exp`}>
                                            <td colSpan={6} style={{
                                                padding: '14px 20px', background: 'var(--bg-2)',
                                                fontSize: 13, color: 'var(--text-2)',
                                                lineHeight: 1.7, whiteSpace: 'pre-wrap',
                                                borderTop: '1px solid var(--border)',
                                            }}>
                                                {v.raw_text}
                                            </td>
                                        </tr>
                                    );
                                }
                                return rows;
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
