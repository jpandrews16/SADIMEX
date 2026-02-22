import { useState } from 'react';
import { mockScorecardsLPZ } from '../data/mockData.js';
import Semaforo from '../components/Semaforo.jsx';
import ScoreRing from '../components/ScoreRing.jsx';

const scoreStyle = s => s >= 80 ? "#16a34a" : s >= 60 ? "#b45309" : "#dc2626";

export default function SupervisorView() {
    const [selected, setSelected] = useState(null);
    const team = mockScorecardsLPZ;
    const verdes = team.filter(v => v.semaforo === "verde").length;
    const rojos = team.filter(v => v.semaforo === "rojo").length;

    return (
        <div className="animate-in">
            <div className="page-header">
                <div className="flex-between">
                    <div>
                        <h2>Mi Equipo — La Paz</h2>
                        <p>Semana 07 · {team.length} vendedores activos · Supervisora: Ingrid Salazar</p>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <span className="pill pill-green">✅ {verdes} verde</span>
                        <span className="pill pill-red">🚨 {rojos} rojo</span>
                    </div>
                </div>
            </div>

            {/* Vendor cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 16 }}>
                {team.map(v => (
                    <div
                        key={v.vendedor_id}
                        className="card"
                        style={{
                            cursor: 'pointer',
                            borderColor: selected === v.vendedor_id ? 'var(--blue)' : undefined,
                            boxShadow: selected === v.vendedor_id ? 'var(--shadow-blue)' : undefined,
                        }}
                        onClick={() => setSelected(selected === v.vendedor_id ? null : v.vendedor_id)}
                    >
                        {/* Header row */}
                        <div className="flex-between" style={{ marginBottom: 16 }}>
                            <div>
                                <div style={{ fontWeight: 700, color: 'var(--text-1)', fontSize: 14 }}>{v.nombre}</div>
                                <div style={{ fontSize: 11.5, color: 'var(--text-3)', marginTop: 2 }}>{v.visitas} visitas · sem. 07</div>
                            </div>
                            <ScoreRing score={v.score} size={60} />
                        </div>

                        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
                            <Semaforo estado={v.semaforo} />
                            <span className="pill pill-blue">🤝 {Math.round(v.tasa_cierre * 100)}% cierre</span>
                            {v.marcas_brecha.length > 0 && (
                                <span className="pill pill-red">⚠️ Brecha</span>
                            )}
                        </div>

                        <div className="score-bar-wrap">
                            <div className="score-bar-track">
                                <div
                                    className={`score-bar-fill ${v.semaforo === 'verde' ? 'green' : v.semaforo === 'rojo' ? 'red' : 'yellow'}`}
                                    style={{ width: `${v.score}%` }}
                                />
                            </div>
                        </div>

                        {/* Expanded detail */}
                        {selected === v.vendedor_id && (
                            <div className="animate-in" style={{ marginTop: 16, paddingTop: 14, borderTop: '1px solid var(--border)' }}>
                                <table style={{ width: '100%', fontSize: 12.5 }}>
                                    <tbody>
                                        {[
                                            ["VP Rate", `${Math.round(v.vp_rate * 100)}%`],
                                            ["Tendencia", v.tendencia === "mejorando" ? "↑ Mejorando" : v.tendencia === "deteriorando" ? "↓ Deteriorando" : "→ Estable"],
                                            ["Brecha", v.marcas_brecha.length ? v.marcas_brecha.join(", ") : "Sin brecha"],
                                        ].map(([k, val]) => (
                                            <tr key={k}>
                                                <td style={{ color: 'var(--text-3)', paddingBottom: 6 }}>{k}</td>
                                                <td style={{ fontWeight: 700, color: 'var(--text-1)', textAlign: 'right', paddingBottom: 6 }}>{val}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                <button className="btn btn-primary mt-16" style={{ width: '100%', justifyContent: 'center', fontSize: 12.5 }}>
                                    📤 Enviar Coaching
                                </button>
                            </div>
                        )}
                    </div>
                ))}
            </div>

            {/* Summary table */}
            <div className="mt-24">
                <div className="section-title">📊 Resumen del Equipo</div>
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>Vendedor</th>
                                <th>Score</th>
                                <th>Estado</th>
                                <th>Visitas</th>
                                <th>Cierre</th>
                                <th>VP Rate</th>
                                <th>Brecha Portafolio</th>
                            </tr>
                        </thead>
                        <tbody>
                            {team.map(v => (
                                <tr key={v.vendedor_id}>
                                    <td><strong>{v.nombre}</strong></td>
                                    <td><span style={{ color: scoreStyle(v.score), fontWeight: 800 }}>{v.score}/100</span></td>
                                    <td><Semaforo estado={v.semaforo} /></td>
                                    <td>{v.visitas}</td>
                                    <td style={{ fontWeight: 600 }}>{Math.round(v.tasa_cierre * 100)}%</td>
                                    <td style={{ fontWeight: 600 }}>{Math.round(v.vp_rate * 100)}%</td>
                                    <td style={{ color: v.marcas_brecha.length ? "#dc2626" : "var(--text-3)" }}>
                                        {v.marcas_brecha.length ? v.marcas_brecha.join(", ") : "✓ Completo"}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
