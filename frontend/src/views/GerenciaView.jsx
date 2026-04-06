import { useMemo } from 'react';
import { cityStats, mockScorecardsLPZ, mockScoreCardsCBBA, mockScorecardsSCZ } from '../data/mockData.js';
import Semaforo from '../components/Semaforo.jsx';

const scoreStyle = s => s >= 80 ? "#16a34a" : s >= 60 ? "#b45309" : "#dc2626";
const semClass = s => s >= 80 ? "green" : s >= 60 ? "yellow" : "red";
const cityLabel = c => ({ LPZ: "La Paz", CBBA: "Cochabamba", SCZ: "Santa Cruz" }[c] || c);

export default function GerenciaView() {
    const allScorecards = useMemo(() =>
        [...mockScorecardsLPZ, ...mockScoreCardsCBBA, ...mockScorecardsSCZ], []);

    const metrics = useMemo(() => ({
        avgScore: Math.round(allScorecards.reduce((a, b) => a + b.score, 0) / (allScorecards.length || 1)),
        verdes: allScorecards.filter(v => v.semaforo === "verde").length,
        amarillos: allScorecards.filter(v => v.semaforo === "amarillo").length,
        rojos: allScorecards.filter(v => v.semaforo === "rojo").length,
        totalQuiebres: Object.values(cityStats).reduce((a, c) => a + c.quiebres, 0),
    }), [allScorecards]);

    const sorted = useMemo(() => [...allScorecards].sort((a, b) => b.score - a.score), [allScorecards]);

    const cityOf = (v) => {
        if (mockScorecardsLPZ.some(s => s.vendedor_id === v.vendedor_id)) return "LPZ";
        if (mockScoreCardsCBBA.some(s => s.vendedor_id === v.vendedor_id)) return "CBBA";
        return "SCZ";
    };

    return (
        <div className="animate-in">
            <div className="page-header">
                <div className="flex-between">
                    <div>
                        <h2>Dashboard Nacional</h2>
                        <p>Semana 07 · Feb 17–21, 2026 · La Paz · Cochabamba · Santa Cruz</p>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                        <span className="pill pill-green">● En vivo</span>
                        <span className="pill pill-blue">Sem. 07</span>
                    </div>
                </div>
            </div>

            <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)' }}>
                <div className={`kpi-card ${semClass(metrics.avgScore)}`}>
                    <div className="kpi-icon">📊</div>
                    <div className="kpi-label">Score Nac.</div>
                    <div className="kpi-value" style={{ color: scoreStyle(metrics.avgScore) }}>{metrics.avgScore}</div>
                    <div className="score-bar-wrap"><div className="score-bar-track"><div className={`score-bar-fill ${semClass(metrics.avgScore)}`} style={{ width: `${metrics.avgScore}%` }} /></div></div>
                </div>
                <div className="kpi-card green">
                    <div className="kpi-icon">✅</div><div className="kpi-label">Verde</div>
                    <div className="kpi-value" style={{ color: '#16a34a' }}>{metrics.verdes}</div><div className="kpi-sub">vendedores</div>
                </div>
                <div className="kpi-card yellow">
                    <div className="kpi-icon">⚠️</div><div className="kpi-label">Amarillo</div>
                    <div className="kpi-value" style={{ color: '#b45309' }}>{metrics.amarillos}</div><div className="kpi-sub">seguimiento</div>
                </div>
                <div className="kpi-card red">
                    <div className="kpi-icon">🚨</div><div className="kpi-label">Rojo</div>
                    <div className="kpi-value" style={{ color: '#dc2626' }}>{metrics.rojos}</div><div className="kpi-sub">acción inmediata</div>
                </div>
                <div className="kpi-card blue">
                    <div className="kpi-icon">📦</div><div className="kpi-label">Quiebres</div>
                    <div className="kpi-value" style={{ color: '#2B5EA8' }}>{metrics.totalQuiebres}</div><div className="kpi-sub">esta semana</div>
                </div>
            </div>

            <div className="mt-24">
                <div className="section-title">🗺️ Performance por Ciudad</div>
                <div className="grid-3">
                    {Object.entries(cityStats).map(([city, s]) => (
                        <div key={city} className="city-card">
                            <div className="city-name">{cityLabel(city)}</div>
                            <div className="city-score" style={{ color: scoreStyle(s.score) }}>{s.score}</div>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                                <span className="pill pill-green">✅ {s.verde}</span>
                                <span className="pill pill-yellow">⚠️ {s.amarillo}</span>
                                <span className="pill pill-red">🚨 {s.rojo}</span>
                            </div>
                            <div className="score-bar-wrap"><div className="score-bar-track"><div className={`score-bar-fill ${semClass(s.score)}`} style={{ width: `${s.score}%` }} /></div></div>
                            <div style={{ fontSize: '11.5px', color: 'var(--text-3)' }}>{s.vendedores} vendedores · {s.quiebres} quiebres detectados</div>
                        </div>
                    ))}
                </div>
            </div>

            <div className="mt-24">
                <div className="section-title">🏆 Ranking Nacional de Vendedores</div>
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <table className="data-table">
                        <thead><tr><th>#</th><th>Vendedor</th><th>Ciudad</th><th>Score</th><th>Estado</th><th>Cierre</th><th>VP Rate</th><th>Tendencia</th></tr></thead>
                        <tbody>
                            {sorted.map((v, i) => (
                                <tr key={v.vendedor_id}>
                                    <td style={{ color: 'var(--text-3)', fontWeight: 700, fontSize: 12 }}>{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `#${i + 1}`}</td>
                                    <td><strong>{v.nombre}</strong></td>
                                    <td><span className="pill pill-blue">{cityOf(v)}</span></td>
                                    <td><span style={{ color: scoreStyle(v.score), fontWeight: 800, fontSize: 14 }}>{v.score}</span></td>
                                    <td><Semaforo estado={v.semaforo} /></td>
                                    <td style={{ fontWeight: 600 }}>{Math.round(v.tasa_cierre * 100)}%</td>
                                    <td style={{ fontWeight: 600 }}>{Math.round(v.vp_rate * 100)}%</td>
                                    <td><span style={{ fontSize: 11.5, fontWeight: 600, color: v.tendencia === "mejorando" ? "#16a34a" : v.tendencia === "deteriorando" ? "#dc2626" : "var(--text-3)" }}>{v.tendencia === "mejorando" ? "↑ Mejorando" : v.tendencia === "deteriorando" ? "↓ Deteriorando" : "→ Estable"}</span></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
