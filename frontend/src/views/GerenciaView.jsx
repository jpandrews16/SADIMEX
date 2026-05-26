import { useState, useEffect, useMemo } from 'react';
import { supabase } from '../auth.js';
import { AnalysisPills, AnalysisDetail } from '../components/AnalysisCard.jsx';

const CIUDAD = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz', NACIONAL: 'Nacional' };
const CITY_ICONS = { LPZ: '🏔️', CBBA: '🌽', SCZ: '🌴' };
const CITIES = ['LPZ', 'CBBA', 'SCZ'];

const fmtDate = d => {
    const diff = (Date.now() - new Date(d)) / 1000;
    if (diff < 3600) return `hace ${Math.round(diff / 60)} min`;
    if (diff < 86400) return `hace ${Math.round(diff / 3600)} h`;
    if (diff < 172800) return 'ayer';
    return new Date(d).toLocaleDateString('es-BO', { day: '2-digit', month: 'short', year: 'numeric' });
};
const fmtDur = s => s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}` : '—';

function ConfBadge({ c }) {
    if (c == null) return <span style={{ color: 'var(--text-3)', fontSize: 12 }}>—</span>;
    const pct = Math.round(c * 100);
    const [color, bg] = c >= 0.85 ? ['#16a34a', '#dcfce7'] : c >= 0.65 ? ['#b45309', '#fef3c7'] : ['#dc2626', '#fee2e2'];
    return <span style={{ fontSize: 11, fontWeight: 700, color, background: bg, padding: '2px 7px', borderRadius: 99 }}>{pct}%</span>;
}

const exportCSV = (rows, filename) => {
    const headers = ['Fecha', 'Vendedor', 'Cliente', 'Ciudad', 'Duración (min)', 'Confianza %',
        'Pedido', 'Monto', 'Productos', 'Quiebre Stock', 'Sentimiento', 'Próximo Paso', 'Transcripción'];
    const data = rows.map(v => {
        const a = v.metadata?.analysis;
        return [
            new Date(v.created_at).toLocaleString('es-BO'),
            v.metadata?.vendedor || '',
            v.metadata?.cliente  || '',
            CIUDAD[v.metadata?.ciudad] || v.metadata?.ciudad || '',
            v.duration_seconds ? (v.duration_seconds / 60).toFixed(1) : '',
            v.confidence_score  ? Math.round(v.confidence_score * 100) : '',
            a ? (a.pedido_capturado ? 'Sí' : 'No') : '',
            a?.monto_aproximado || '',
            (a?.productos_mencionados || []).join('; '),
            (a?.quiebre_stock || []).join('; '),
            a?.sentimiento_cliente || '',
            a?.proximo_paso || '',
            (v.raw_text || '').replace(/[\n\r]+/g, ' '),
        ];
    });
    const csv = [headers, ...data]
        .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
        .join('\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a); URL.revokeObjectURL(url);
};

export default function GerenciaView({ currentUser }) {
    const [visits, setVisits]   = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError]     = useState('');
    const [search, setSearch]   = useState('');
    const [cityFilter, setCityFilter] = useState('all');
    const [expanded, setExpanded]     = useState(null);

    useEffect(() => {
        if (!currentUser) return;
        supabase.auth.getSession().then(({ data: { session } }) => {
            fetch('/api/visits', { headers: { Authorization: `Bearer ${session?.access_token}` } })
                .then(r => r.json())
                .then(d => { if (!d.ok) setError(d.error || 'Error'); else setVisits(d.visits || []); })
                .catch(e => setError(e.message))
                .finally(() => setLoading(false));
        });
    }, [currentUser?.id]);

    const thisWeek = useMemo(
        () => visits.filter(v => (Date.now() - new Date(v.created_at)) / 86400000 < 7).length,
        [visits]
    );
    const pedidosPct = useMemo(() => {
        const withAnalysis = visits.filter(v => v.metadata?.analysis);
        if (!withAnalysis.length) return null;
        const captured = withAnalysis.filter(v => v.metadata.analysis.pedido_capturado).length;
        return Math.round((captured / withAnalysis.length) * 100);
    }, [visits]);

    const byCity = useMemo(() => {
        const map = { LPZ: 0, CBBA: 0, SCZ: 0, NACIONAL: 0 };
        visits.forEach(v => { const c = v.metadata?.ciudad; if (c && map[c] !== undefined) map[c]++; });
        return map;
    }, [visits]);

    const topVendedores = useMemo(() => {
        const map = {};
        visits.forEach(v => {
            const name = v.metadata?.vendedor || 'Sin nombre';
            if (!map[name]) map[name] = { count: 0, pedidos: 0 };
            map[name].count++;
            if (v.metadata?.analysis?.pedido_capturado) map[name].pedidos++;
        });
        return Object.entries(map).sort((a, b) => b[1].count - a[1].count).slice(0, 5);
    }, [visits]);

    const filtered = useMemo(() =>
        visits.filter(v => {
            const q = search.toLowerCase();
            const matchSearch = !search ||
                (v.metadata?.cliente  || '').toLowerCase().includes(q) ||
                (v.metadata?.vendedor || '').toLowerCase().includes(q) ||
                (v.raw_text           || '').toLowerCase().includes(q);
            const matchCity = cityFilter === 'all' || v.metadata?.ciudad === cityFilter;
            return matchSearch && matchCity;
        }),
        [visits, search, cityFilter]
    );

    if (loading) return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '40vh', color: 'var(--text-3)', fontSize: 13 }}>
            Cargando dashboard...
        </div>
    );

    return (
        <div className="animate-in">
            <div className="page-header">
                <div className="flex-between">
                    <div>
                        <h2>Dashboard Nacional</h2>
                        <p>{visits.length} visitas · {thisWeek} esta semana</p>
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
            <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)', marginBottom: 24 }}>
                {[
                    { icon: '📋', label: 'Total visitas',   val: visits.length,                        cls: 'blue'  },
                    { icon: '📅', label: 'Esta semana',     val: thisWeek,                             cls: 'green' },
                    { icon: '✅', label: 'Efectividad',     val: pedidosPct != null ? `${pedidosPct}%` : '—', cls: 'green' },
                    { icon: '🌽', label: 'Cochabamba',      val: byCity.CBBA,                          cls: 'yellow' },
                ].map(s => (
                    <div key={s.label} className={`kpi-card ${s.cls}`}>
                        <div className="kpi-icon">{s.icon}</div>
                        <div className="kpi-label">{s.label}</div>
                        <div className="kpi-value">{s.val}</div>
                    </div>
                ))}
            </div>

            {/* Ciudad + Top vendedores */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 28 }}>

                <div>
                    <div className="section-title">🗺️ Visitas por Ciudad</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {CITIES.map(c => {
                            const count = byCity[c] || 0;
                            const pct   = visits.length > 0 ? Math.round(count / visits.length * 100) : 0;
                            return (
                                <div key={c} className="card" style={{ padding: '14px 16px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                                        <span style={{ fontWeight: 700, fontSize: 13 }}>{CITY_ICONS[c]} {CIUDAD[c]}</span>
                                        <span style={{ fontWeight: 800, fontSize: 16, color: 'var(--blue)' }}>{count}</span>
                                    </div>
                                    <div style={{ background: 'var(--bg-3)', borderRadius: 99, height: 5, overflow: 'hidden' }}>
                                        <div style={{ height: '100%', borderRadius: 99, background: 'var(--blue)', width: `${pct}%`, transition: 'width 0.4s ease' }} />
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-3)', marginTop: 4 }}>{pct}% del total</div>
                                </div>
                            );
                        })}
                    </div>
                </div>

                <div>
                    <div className="section-title">🏆 Top Vendedores</div>
                    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                        {topVendedores.length === 0 ? (
                            <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-3)', fontSize: 13 }}>Sin datos aún</div>
                        ) : (
                            <table className="data-table">
                                <tbody>
                                    {topVendedores.map(([name, stats], i) => (
                                        <tr key={name}>
                                            <td style={{ width: 32, fontWeight: 800, fontSize: 15 }}>
                                                {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i + 1}`}
                                            </td>
                                            <td><strong style={{ fontSize: 13 }}>{name}</strong></td>
                                            <td style={{ fontSize: 12, color: 'var(--text-3)' }}>
                                                {stats.pedidos} pedido{stats.pedidos !== 1 ? 's' : ''}
                                            </td>
                                            <td style={{ textAlign: 'right' }}>
                                                <span style={{ fontWeight: 800, color: 'var(--blue)', fontSize: 14 }}>{stats.count}</span>
                                                <span style={{ fontSize: 11, color: 'var(--text-3)', marginLeft: 3 }}>vis.</span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        )}
                    </div>
                </div>
            </div>

            {/* Buscador + tabla */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                <div className="section-title" style={{ margin: 0 }}>🔍 Todas las Visitas</div>
                <button
                    onClick={() => exportCSV(filtered, `sadimex_visitas_${new Date().toISOString().slice(0, 10)}.csv`)}
                    style={{
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        borderRadius: 'var(--r-sm)', padding: '7px 14px',
                        fontSize: 12.5, fontWeight: 600, color: 'var(--text-2)',
                        cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                    }}
                    onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--blue)'}
                    onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
                >
                    📥 Exportar Excel ({filtered.length})
                </button>
            </div>

            <div style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
                <input
                    value={search}
                    onChange={e => { setSearch(e.target.value); setExpanded(null); }}
                    placeholder="Buscar por cliente, vendedor o texto de la visita..."
                    style={{
                        flex: 1, background: 'var(--bg-2)', border: '1px solid var(--border)',
                        borderRadius: 'var(--r-sm)', padding: '10px 14px',
                        color: 'var(--text-1)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
                    }}
                />
                <select value={cityFilter} onChange={e => setCityFilter(e.target.value)}
                    style={{
                        background: 'var(--bg-2)', border: '1px solid var(--border)',
                        borderRadius: 'var(--r-sm)', padding: '10px 12px',
                        color: 'var(--text-1)', fontSize: 13, outline: 'none', cursor: 'pointer', fontFamily: 'inherit',
                    }}>
                    <option value="all">Todas las ciudades</option>
                    {CITIES.map(c => <option key={c} value={c}>{CIUDAD[c]}</option>)}
                </select>
            </div>

            {filtered.length === 0 ? (
                <div className="card" style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-3)' }}>
                    <div style={{ fontSize: 36, marginBottom: 12 }}>🕵️</div>
                    <p>{visits.length === 0 ? 'Todavía no hay visitas en el sistema.' : 'Sin resultados.'}</p>
                </div>
            ) : (
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    {search && (
                        <div style={{ padding: '9px 20px', background: 'var(--bg-2)', borderBottom: '1px solid var(--border)', fontSize: 12, color: 'var(--text-3)' }}>
                            {filtered.length} resultado{filtered.length !== 1 ? 's' : ''} para "<strong style={{ color: 'var(--text-2)' }}>{search}</strong>"
                        </div>
                    )}
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Fecha</th>
                                <th>Vendedor</th>
                                <th>Cliente</th>
                                <th>Ciudad</th>
                                <th>Dur.</th>
                                <th>Análisis IA</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.flatMap(v => {
                                const a = v.metadata?.analysis;
                                const rows = [
                                    <tr key={v.id} style={{ cursor: 'pointer' }}
                                        onClick={() => setExpanded(expanded === v.id ? null : v.id)}>
                                        <td style={{ fontSize: 12, color: 'var(--text-3)', whiteSpace: 'nowrap' }}>{fmtDate(v.created_at)}</td>
                                        <td><strong style={{ fontSize: 13 }}>{v.metadata?.vendedor || '—'}</strong></td>
                                        <td style={{ fontSize: 13 }}>{v.metadata?.cliente || '—'}</td>
                                        <td>
                                            <span className="pill pill-blue" style={{ fontSize: 11 }}>
                                                {CITY_ICONS[v.metadata?.ciudad]} {CIUDAD[v.metadata?.ciudad] || v.metadata?.ciudad || '—'}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: 12, color: 'var(--text-3)' }}>{fmtDur(v.duration_seconds)}</td>
                                        <td><AnalysisPills a={a} /></td>
                                        <td style={{ color: 'var(--text-3)', fontSize: 11 }}>{expanded === v.id ? '▲' : '▼'}</td>
                                    </tr>
                                ];
                                if (expanded === v.id) {
                                    rows.push(
                                        <tr key={`${v.id}-exp`}>
                                            <td colSpan={7} style={{ padding: '16px 20px', background: 'var(--bg-2)', borderTop: '1px solid var(--border)' }}>
                                                <div style={{ marginBottom: 14 }}>
                                                    <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>🧠 Análisis IA</div>
                                                    <AnalysisDetail a={a} />
                                                </div>
                                                {v.raw_text && (
                                                    <>
                                                        <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>🎙️ Transcripción</div>
                                                        <div style={{ fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.7, whiteSpace: 'pre-wrap', maxHeight: 240, overflowY: 'auto' }}>
                                                            {v.raw_text}
                                                        </div>
                                                    </>
                                                )}
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
