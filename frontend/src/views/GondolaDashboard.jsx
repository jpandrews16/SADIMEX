import { useEffect, useMemo, useState } from 'react';
import GondolaResultado, { ListaHallazgos, ScoreBadge } from '../components/GondolaResultado.jsx';
import {
    hallazgosPrioritarios, traerHistorial, traerNombres,
    traerRanking, traerSaludSalas,
} from '../gondola.js';

/**
 * Tablero de ejecución en sala.
 *
 * Abre en "Qué corregir", no en gráficos: lo primero que un supervisor
 * necesita al abrir esto es la lista de lo que hay que ir a arreglar hoy.
 */

const CIUDAD_LABEL = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz', ALL: 'Nacional' };

const card = {
    background: 'var(--bg)', border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)', padding: 20, boxShadow: 'var(--shadow-sm)',
};

const th = {
    textAlign: 'left', fontSize: 10.5, fontWeight: 800, color: 'var(--text-3)',
    textTransform: 'uppercase', letterSpacing: '0.8px', padding: '0 10px 10px',
    borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
};

const td = {
    fontSize: 13, color: 'var(--text-1)', padding: '12px 10px',
    borderBottom: '1px solid var(--border-2)',
};

function KPI({ etiqueta, valor, sufijo = '', color }) {
    return (
        <div style={{ ...card, flex: '1 1 150px', minWidth: 150, padding: 18 }}>
            <div style={{ fontSize: 10.5, fontWeight: 800, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.9px', marginBottom: 6 }}>
                {etiqueta}
            </div>
            <div style={{ fontSize: 26, fontWeight: 800, color: color || 'var(--text-1)', lineHeight: 1.1 }}>
                {valor ?? '—'}{valor != null ? sufijo : ''}
            </div>
        </div>
    );
}

function Tabs({ activa, onCambio, opciones }) {
    return (
        <div style={{ display: 'flex', gap: 4, marginBottom: 20, borderBottom: '1px solid var(--border)', overflowX: 'auto' }}>
            {opciones.map(o => (
                <button
                    key={o.id}
                    onClick={() => onCambio(o.id)}
                    style={{
                        background: 'none', border: 'none', cursor: 'pointer',
                        padding: '10px 14px', fontSize: 13.5, fontFamily: 'inherit',
                        fontWeight: activa === o.id ? 800 : 600,
                        color: activa === o.id ? 'var(--blue)' : 'var(--text-3)',
                        borderBottom: `2px solid ${activa === o.id ? 'var(--blue)' : 'transparent'}`,
                        marginBottom: -1, whiteSpace: 'nowrap',
                    }}
                >
                    {o.label}
                </button>
            ))}
        </div>
    );
}

function Vacio({ mensaje }) {
    return (
        <div style={{ ...card, textAlign: 'center', padding: '44px 20px' }}>
            <p style={{ margin: 0, fontSize: 13.5, color: 'var(--text-3)', lineHeight: 1.6 }}>{mensaje}</p>
        </div>
    );
}

export default function GondolaDashboard({ currentUser }) {
    const esNacional = currentUser?.rol === 'gerente' || currentUser?.rol === 'admin';
    const ciudad = esNacional ? 'ALL' : currentUser?.ciudad;

    const [tab, setTab] = useState('corregir');
    const [cargando, setCargando] = useState(true);
    const [error, setError] = useState('');

    const [historial, setHistorial] = useState([]);
    const [ranking, setRanking] = useState([]);
    const [salas, setSalas] = useState([]);
    const [nombres, setNombres] = useState({});
    const [detalle, setDetalle] = useState(null);

    useEffect(() => {
        let vivo = true;
        setCargando(true);
        (async () => {
            try {
                const [h, r, s] = await Promise.all([
                    traerHistorial({ ciudad }),
                    traerRanking(ciudad),
                    traerSaludSalas(ciudad),
                ]);
                if (!vivo) return;
                setHistorial(h);
                setRanking(r);
                setSalas(s);
                setNombres(await traerNombres([...r.map(x => x.reponedor_id), ...h.map(x => x.reponedor_id)]));
                setError('');
            } catch (err) {
                if (vivo) setError(err.message || 'No se pudieron cargar los datos.');
            } finally {
                if (vivo) setCargando(false);
            }
        })();
        return () => { vivo = false; };
    }, [ciudad]);

    const kpis = useMemo(() => {
        if (!historial.length) return null;
        const scores = historial.map(a => a.score).filter(n => typeof n === 'number');
        const shares = historial.map(a => a.share_of_shelf_pct).filter(n => typeof n === 'number');
        return {
            fotos: historial.length,
            score: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null,
            share: shares.length ? Math.round(shares.reduce((a, b) => a + b, 0) / shares.length) : null,
            quiebres: historial.reduce((n, a) => n + (a.quiebres_detectados || 0), 0),
            rojas: historial.filter(a => a.semaforo === 'rojo').length,
        };
    }, [historial]);

    const hallazgos = useMemo(() => hallazgosPrioritarios(historial), [historial]);
    const nombreDe = id => nombres[id] || `${String(id).slice(0, 8)}…`;

    if (cargando) {
        return (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-3)', fontSize: 13, fontWeight: 600 }}>
                ⏳ Cargando ejecución en sala...
            </div>
        );
    }

    if (detalle) {
        return (
            <div style={{ maxWidth: 760, margin: '0 auto', padding: '28px 20px 60px' }}>
                <button onClick={() => setDetalle(null)} style={{
                    background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                    marginBottom: 16, fontSize: 13, fontWeight: 700, color: 'var(--blue)', fontFamily: 'inherit',
                }}>
                    ← Volver al tablero
                </button>
                <GondolaResultado analisis={detalle} />
            </div>
        );
    }

    return (
        <div style={{ maxWidth: 1080, margin: '0 auto', padding: '28px 20px 60px' }}>
            <div style={{ marginBottom: 22 }}>
                <h2 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 800, color: 'var(--text-1)' }}>
                    🛒 Ejecución en sala
                </h2>
                <p style={{ margin: 0, fontSize: 13.5, color: 'var(--text-3)' }}>
                    {CIUDAD_LABEL[ciudad] || ciudad} · últimos 30 días
                </p>
            </div>

            {error && (
                <div style={{ padding: '14px 16px', marginBottom: 18, background: 'var(--red-bg)', border: '1px solid var(--red-border)', borderRadius: 'var(--r)' }}>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>{error}</p>
                </div>
            )}

            {kpis && (
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
                    <KPI etiqueta="Score promedio" valor={kpis.score} />
                    <KPI etiqueta="Share of shelf" valor={kpis.share} sufijo="%" />
                    <KPI etiqueta="Góndolas auditadas" valor={kpis.fotos} />
                    <KPI etiqueta="Quiebres" valor={kpis.quiebres} color={kpis.quiebres ? 'var(--red)' : undefined} />
                    <KPI etiqueta="En rojo" valor={kpis.rojas} color={kpis.rojas ? 'var(--red)' : undefined} />
                </div>
            )}

            <Tabs
                activa={tab}
                onCambio={setTab}
                opciones={[
                    { id: 'corregir', label: `Qué corregir (${hallazgos.length})` },
                    { id: 'reponedores', label: 'Reponedores' },
                    { id: 'salas', label: 'Salas' },
                    { id: 'historial', label: 'Historial' },
                ]}
            />

            {/* Lo primero que necesita un supervisor: la lista de tareas */}
            {tab === 'corregir' && (
                historial.length
                    ? <ListaHallazgos hallazgos={hallazgos} titulo="Prioridades de esta semana" />
                    : <Vacio mensaje="Todavía no hay góndolas auditadas. En cuanto los reponedores suban fotos, acá aparece qué hay que corregir." />
            )}

            {tab === 'reponedores' && (
                ranking.length ? (
                    <div style={{ ...card, overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 620 }}>
                            <thead>
                                <tr>
                                    <th style={th}>Reponedor</th>
                                    <th style={th}>Score</th>
                                    <th style={th}>Fotos</th>
                                    <th style={th}>Verdes</th>
                                    <th style={th}>Rojas</th>
                                    <th style={th}>Share</th>
                                    <th style={th}>Salas</th>
                                    <th style={th}>Última</th>
                                </tr>
                            </thead>
                            <tbody>
                                {ranking.map(r => (
                                    <tr key={r.reponedor_id}>
                                        <td style={{ ...td, fontWeight: 700 }}>{nombreDe(r.reponedor_id)}</td>
                                        <td style={td}>
                                            <ScoreBadge
                                                score={Math.round(r.score_promedio || 0)}
                                                semaforo={r.score_promedio >= 80 ? 'verde' : r.score_promedio >= 60 ? 'amarillo' : 'rojo'}
                                                size="chico"
                                            />
                                        </td>
                                        <td style={td}>{r.fotos_analizadas}</td>
                                        <td style={{ ...td, color: 'var(--green)', fontWeight: 700 }}>{r.fotos_verdes}</td>
                                        <td style={{ ...td, color: r.fotos_rojas ? 'var(--red)' : 'var(--text-3)', fontWeight: 700 }}>{r.fotos_rojas}</td>
                                        <td style={td}>{r.share_promedio != null ? `${r.share_promedio}%` : '—'}</td>
                                        <td style={td}>{r.salas_cubiertas}</td>
                                        <td style={{ ...td, color: 'var(--text-3)', fontSize: 12 }}>
                                            {r.ultima_foto ? new Date(r.ultima_foto).toLocaleDateString('es-BO') : '—'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                        <p style={{ margin: '14px 0 0', fontSize: 11.5, color: 'var(--text-4)', lineHeight: 1.5 }}>
                            El score sale de las 6 reglas de ejecución, calculadas sobre cada foto.
                            Las reglas que la foto no permitía evaluar no cuentan.
                        </p>
                    </div>
                ) : <Vacio mensaje="Sin datos de reponedores todavía." />
            )}

            {tab === 'salas' && (
                salas.length ? (
                    <div style={{ ...card, overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 560 }}>
                            <thead>
                                <tr>
                                    <th style={th}>Sala</th>
                                    <th style={th}>Cadena</th>
                                    <th style={th}>Score</th>
                                    <th style={th}>Fotos</th>
                                    <th style={th}>Quiebres</th>
                                    <th style={th}>Última auditoría</th>
                                </tr>
                            </thead>
                            <tbody>
                                {salas.map(s => (
                                    <tr key={s.sala_id}>
                                        <td style={{ ...td, fontWeight: 700 }}>{s.sala}</td>
                                        <td style={td}>{s.cadena}</td>
                                        <td style={{ ...td, fontWeight: 800 }}>{s.score_promedio ?? '—'}</td>
                                        <td style={td}>{s.fotos_30d}</td>
                                        <td style={{ ...td, color: s.quiebres_30d ? 'var(--red)' : 'var(--text-3)' }}>{s.quiebres_30d ?? 0}</td>
                                        <td style={td}>
                                            {s.ultima_auditoria
                                                ? <span style={{ fontSize: 12, color: 'var(--text-3)' }}>{new Date(s.ultima_auditoria).toLocaleDateString('es-BO')}</span>
                                                : <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--red)' }}>Sin visitar</span>}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : <Vacio mensaje="No hay salas cargadas. El administrador debe registrarlas primero." />
            )}

            {tab === 'historial' && (
                historial.length ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                        {historial.map(a => (
                            <button
                                key={a.id}
                                onClick={() => setDetalle(a)}
                                style={{
                                    ...card, display: 'flex', alignItems: 'center', gap: 14,
                                    cursor: 'pointer', textAlign: 'left', fontFamily: 'inherit', padding: 16,
                                }}
                            >
                                <ScoreBadge score={a.score} semaforo={a.semaforo} size="chico" />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-1)', marginBottom: 3 }}>
                                        {a.salas?.cadenas?.nombre ? `${a.salas.cadenas.nombre} — ` : ''}{a.salas?.nombre || 'Sala'}
                                    </div>
                                    <div style={{ fontSize: 12, color: 'var(--text-3)' }}>
                                        {nombreDe(a.reponedor_id)} · {new Date(a.created_at).toLocaleDateString('es-BO')}
                                        {a.share_of_shelf_pct != null ? ` · ${a.share_of_shelf_pct}% share` : ''}
                                        {a.quiebres_detectados ? ` · ${a.quiebres_detectados} quiebre(s)` : ''}
                                    </div>
                                </div>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-4)', flexShrink: 0 }}>
                                    {(a.hallazgos || []).length} obs. →
                                </span>
                            </button>
                        ))}
                    </div>
                ) : <Vacio mensaje="Sin auditorías registradas." />
            )}
        </div>
    );
}
