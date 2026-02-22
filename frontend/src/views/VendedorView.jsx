import { useState } from 'react';
import { mockVisitaDemo } from '../data/mockData.js';
import Semaforo from '../components/Semaforo.jsx';
import ScoreRing from '../components/ScoreRing.jsx';

const catStyle = {
    portafolio: { icon: '📦', bg: '#eff6ff', color: '#1d4ed8' },
    cierre: { icon: '🤝', bg: '#f0fdf4', color: '#15803d' },
    relacion_cliente: { icon: '💬', bg: '#fff7ed', color: '#c2410c' },
    precio: { icon: '💰', bg: '#fefce8', color: '#a16207' },
    general: { icon: '📋', bg: '#f8fafc', color: '#475569' },
};

export default function VendedorView() {
    const v = mockVisitaDemo;
    const [tab, setTab] = useState("resumen");

    return (
        <div className="animate-in">
            <div className="page-header">
                <div className="flex-between">
                    <div>
                        <h2>Mi Último Reporte</h2>
                        <p>{v.fecha} · {v.cliente} · La Paz</p>
                    </div>
                    <Semaforo estado={v.semaforo} />
                </div>
            </div>

            {/* Hero */}
            <div className="card" style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', gap: 28, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ScoreRing score={v.score_visita} size={108} />
                    <div style={{ flex: 1, minWidth: 200 }}>
                        <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>
                            Resumen Ejecutivo · IA
                        </div>
                        <p style={{ fontSize: 13.5, color: 'var(--text-2)', lineHeight: 1.65 }}>{v.resumen_ejecutivo}</p>
                        <div style={{ display: 'flex', gap: 6, marginTop: 14, flexWrap: 'wrap' }}>
                            {v.kpis.cierre_exitoso && <span className="pill pill-green">✅ Cierre exitoso</span>}
                            {v.kpis.saludo_adecuado && <span className="pill pill-green">👋 Buen saludo</span>}
                            {v.kpis.quiebre_de_stock_detectado && <span className="pill pill-yellow">📦 Quiebre detectado</span>}
                            {v.kpis.marcas_faltantes?.length === 0 && <span className="pill pill-green">✅ Portafolio completo</span>}
                        </div>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div style={{ display: 'flex', gap: 4, marginBottom: 18 }}>
                {[
                    { key: "resumen", label: "💡 Coaching" },
                    { key: "kpis", label: "📊 KPIs" },
                    { key: "transcripcion", label: "🎙️ Diálogo" },
                ].map(t => (
                    <button key={t.key} className={`role-btn ${tab === t.key ? "active" : ""}`} onClick={() => setTab(t.key)}>
                        {t.label}
                    </button>
                ))}
            </div>

            {/* Coaching */}
            {tab === "resumen" && (
                <div className="animate-in">
                    <div className="section-title">💡 Coaching Insights · Gemini 2.5</div>
                    {v.coaching_insights.map((ins, i) => {
                        const s = catStyle[ins.categoria] || catStyle.general;
                        return (
                            <div key={i} className="coaching-card">
                                <div className="coaching-cat-dot" style={{ background: s.bg }}>
                                    {s.icon}
                                </div>
                                <div style={{ flex: 1 }}>
                                    <div className="cat-label">{ins.categoria.replace("_", " ")}</div>
                                    <div style={{ fontSize: 12, color: 'var(--text-3)', marginTop: 3, fontStyle: 'italic' }}>
                                        {ins.observacion}
                                    </div>
                                    <div className="insight-text" style={{ marginTop: 6 }}>
                                        {ins.sugerencia_tactica}
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* KPIs */}
            {tab === "kpis" && (
                <div className="animate-in">
                    <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))' }}>
                        {[
                            { label: "Score VP", value: `${v.kpis.venta_perfecta_score}/100`, icon: "📊", cls: "yellow" },
                            { label: "Cierre", value: v.kpis.cierre_exitoso ? "Exitoso" : "No cerrado", icon: "🤝", cls: "green" },
                            { label: "Técnica", value: v.kpis.tecnica_cierre_usada || "—", icon: "🎯", cls: "blue" },
                            { label: "Marcas", value: v.kpis.marcas_mencionadas.join(", "), icon: "📦", cls: "green" },
                            { label: "Faltantes", value: v.kpis.marcas_faltantes.length ? v.kpis.marcas_faltantes.join(", ") : "Ninguna", icon: "⚠️", cls: "green" },
                            { label: "Quiebre stock", value: v.kpis.quiebre_de_stock_detectado ? "Detectado" : "Sin quiebre", icon: "🏬", cls: "yellow" },
                            { label: "Precio correcto", value: v.kpis.precio_correcto ? "Correcto" : "Incorrecto", icon: "💰", cls: "green" },
                            { label: "Saludo", value: v.kpis.saludo_adecuado ? "Adecuado" : "Incorrecto", icon: "👋", cls: "green" },
                        ].map((k, i) => (
                            <div key={i} className={`kpi-card ${k.cls}`}>
                                <div className="kpi-icon">{k.icon}</div>
                                <div className="kpi-label">{k.label}</div>
                                <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)', marginTop: 6 }}>{k.value}</div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Transcript */}
            {tab === "transcripcion" && (
                <div className="animate-in">
                    <div className="section-title">🎙️ Transcripción Diarizada · Gemini 2.5 Pro</div>
                    <div className="card" style={{ padding: 24 }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                            {v.segmentos.map((seg, i) => (
                                <div key={i} style={{ display: 'flex', gap: 10, flexDirection: seg.speaker === "VENDEDOR" ? "row" : "row-reverse" }}>
                                    <div style={{
                                        width: 34, height: 34, borderRadius: '50%', flexShrink: 0,
                                        background: seg.speaker === "VENDEDOR" ? '#eff6ff' : '#f0fdf4',
                                        border: `1.5px solid ${seg.speaker === "VENDEDOR" ? '#93c5fd' : '#86efac'}`,
                                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13
                                    }}>
                                        {seg.speaker === "VENDEDOR" ? "🧑‍💼" : "🏪"}
                                    </div>
                                    <div style={{ flex: 1, maxWidth: '72%' }}>
                                        <div style={{
                                            fontSize: 9.5, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase',
                                            color: seg.speaker === "VENDEDOR" ? '#2B5EA8' : '#15803d',
                                            marginBottom: 4, textAlign: seg.speaker === "VENDEDOR" ? "left" : "right"
                                        }}>
                                            {seg.speaker}
                                        </div>
                                        <div style={{
                                            background: seg.speaker === "VENDEDOR" ? '#eff6ff' : '#f0fdf4',
                                            border: `1px solid ${seg.speaker === "VENDEDOR" ? '#bfdbfe' : '#bbf7d0'}`,
                                            borderRadius: seg.speaker === "VENDEDOR" ? '2px 10px 10px 10px' : '10px 2px 10px 10px',
                                            padding: '9px 13px',
                                            fontSize: 13.5, color: 'var(--text-1)', lineHeight: 1.5
                                        }}>
                                            {seg.texto}
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
