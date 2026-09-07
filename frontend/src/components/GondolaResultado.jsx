import { REGLA_LABEL, SEMAFORO_COLOR, SEVERIDAD } from '../gondola.js';

/**
 * Resultado de una foto de góndola.
 *
 * El orden no es casual: primero el score, después las tareas concretas y
 * al final el detalle por regla. El supervisor necesita saber qué mandar a
 * arreglar, no leer un informe.
 */

const card = {
    background: 'var(--bg)', border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)', padding: 20, boxShadow: 'var(--shadow-sm)',
};

export function ScoreBadge({ score, semaforo, size = 'grande' }) {
    const s = SEMAFORO_COLOR[semaforo] || SEMAFORO_COLOR.rojo;
    const grande = size === 'grande';
    return (
        <div style={{
            display: 'inline-flex', flexDirection: 'column', alignItems: 'center',
            justifyContent: 'center', flexShrink: 0,
            width: grande ? 96 : 56, height: grande ? 96 : 56,
            borderRadius: '50%', background: s.bg, border: `3px solid ${s.border}`,
        }}>
            <span style={{ fontSize: grande ? 30 : 18, fontWeight: 800, color: s.color, lineHeight: 1 }}>
                {score}
            </span>
            {grande && (
                <span style={{ fontSize: 10, fontWeight: 700, color: s.color, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    de 100
                </span>
            )}
        </div>
    );
}

function BarraRegla({ nombre, resultado }) {
    const pct = Math.round((resultado.cumplimiento ?? 0) * 100);
    const color = resultado.cumple ? 'var(--green)' : pct >= 50 ? 'var(--yellow)' : 'var(--red)';

    return (
        <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 5, gap: 10 }}>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-1)' }}>
                    {resultado.cumple ? '✅' : '⚠️'} {REGLA_LABEL[nombre] || nombre}
                </span>
                <span style={{ fontSize: 12.5, fontWeight: 800, color, flexShrink: 0 }}>{pct}%</span>
            </div>
            <div style={{ height: 5, background: 'var(--bg-3)', borderRadius: 3, overflow: 'hidden', marginBottom: 5 }}>
                <div style={{ width: `${pct}%`, height: '100%', background: color, transition: 'width .3s' }} />
            </div>
            {resultado.detalle && (
                <p style={{ margin: 0, fontSize: 12, color: 'var(--text-3)', lineHeight: 1.45 }}>
                    {resultado.detalle}
                </p>
            )}
        </div>
    );
}

function Hallazgo({ hallazgo }) {
    const sev = SEVERIDAD[hallazgo.severidad] || SEVERIDAD.bajo;
    const esUrgente = hallazgo.severidad === 'critico' || hallazgo.severidad === 'alto';

    return (
        <li style={{
            listStyle: 'none', padding: '12px 14px', marginBottom: 8,
            background: esUrgente ? 'var(--red-bg)' : 'var(--bg-2)',
            border: `1px solid ${esUrgente ? 'var(--red-border)' : 'var(--border)'}`,
            borderRadius: 'var(--r)',
        }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{ fontSize: 13, flexShrink: 0 }}>{sev.emoji}</span>
                <div style={{ minWidth: 0 }}>
                    <p style={{ margin: '0 0 4px', fontSize: 13, fontWeight: 700, color: 'var(--text-1)', lineHeight: 1.4 }}>
                        {hallazgo.mensaje}
                    </p>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--text-2)', lineHeight: 1.45 }}>
                        → {hallazgo.accion}
                    </p>
                    {(hallazgo.sala || hallazgo.fecha) && (
                        <p style={{ margin: '6px 0 0', fontSize: 11.5, color: 'var(--text-3)' }}>
                            {hallazgo.cadena ? `${hallazgo.cadena} · ` : ''}{hallazgo.sala}
                            {hallazgo.fecha ? ` · ${new Date(hallazgo.fecha).toLocaleDateString('es-BO')}` : ''}
                        </p>
                    )}
                </div>
            </div>
        </li>
    );
}

export function ListaHallazgos({ hallazgos, titulo = 'Qué hay que corregir' }) {
    if (!hallazgos?.length) {
        return (
            <div style={{ ...card, background: 'var(--green-bg)', border: '1px solid var(--green-border)' }}>
                <p style={{ margin: 0, fontSize: 13.5, fontWeight: 700, color: 'var(--green)' }}>
                    ✅ Sin observaciones. La góndola cumple todas las reglas.
                </p>
            </div>
        );
    }

    return (
        <div>
            <h4 style={{ margin: '0 0 12px', fontSize: 12, fontWeight: 800, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                {titulo} ({hallazgos.length})
            </h4>
            <ul style={{ margin: 0, padding: 0 }}>
                {hallazgos.map((h, i) => <Hallazgo key={i} hallazgo={h} />)}
            </ul>
        </div>
    );
}

function Metrica({ etiqueta, valor, sufijo = '' }) {
    return (
        <div style={{ flex: '1 1 90px', minWidth: 90 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '0.8px', marginBottom: 3 }}>
                {etiqueta}
            </div>
            <div style={{ fontSize: 19, fontWeight: 800, color: 'var(--text-1)' }}>
                {valor ?? '—'}{valor != null ? sufijo : ''}
            </div>
        </div>
    );
}

export default function GondolaResultado({ analisis }) {
    if (!analisis) return null;

    const s = SEMAFORO_COLOR[analisis.semaforo] || SEMAFORO_COLOR.rojo;
    const reglas = analisis.reglas || {};
    const obs = analisis.observacion || {};
    const detectados = (obs.detecciones || []).length;
    const confianzaBaja = (analisis.confianza_global ?? 1) < 0.7;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* Encabezado con el score */}
            <div style={{ ...card, background: s.bg, border: `1px solid ${s.border}` }}>
                <div style={{ display: 'flex', gap: 18, alignItems: 'center', flexWrap: 'wrap' }}>
                    <ScoreBadge score={analisis.score} semaforo={analisis.semaforo} />
                    <div style={{ minWidth: 200, flex: 1 }}>
                        <div style={{ fontSize: 11, fontWeight: 800, color: s.color, textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 4 }}>
                            {s.label}
                        </div>
                        <h3 style={{ margin: '0 0 8px', fontSize: 17, fontWeight: 800, color: 'var(--text-1)' }}>
                            {analisis.salas?.cadenas?.nombre ? `${analisis.salas.cadenas.nombre} — ` : ''}
                            {analisis.salas?.nombre || 'Góndola analizada'}
                        </h3>
                        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                            <Metrica etiqueta="Share of shelf" valor={analisis.share_of_shelf_pct} sufijo="%" />
                            <Metrica etiqueta="SKU detectados" valor={detectados} />
                            <Metrica etiqueta="Quiebres" valor={analisis.quiebres_detectados} />
                        </div>
                    </div>
                </div>
            </div>

            {/* La confianza baja cambia cómo hay que leer todo lo demás */}
            {(confianzaBaja || analisis.calidad_foto === 'mala') && (
                <div style={{
                    padding: '12px 14px', background: 'var(--yellow-bg)',
                    border: '1px solid var(--yellow-border)', borderRadius: 'var(--r)',
                }}>
                    <p style={{ margin: 0, fontSize: 12.5, color: 'var(--yellow)', fontWeight: 600, lineHeight: 1.5 }}>
                        ⚠️ Lectura poco confiable ({Math.round((analisis.confianza_global ?? 0) * 100)}% de confianza
                        {analisis.calidad_foto ? `, foto ${analisis.calidad_foto}` : ''}).
                        Conviene repetir la foto antes de tomar decisiones con este resultado.
                    </p>
                </div>
            )}

            <ListaHallazgos hallazgos={analisis.hallazgos} />

            {/* Detalle por regla: el "por qué" del score */}
            {Object.keys(reglas).length > 0 && (
                <div style={card}>
                    <h4 style={{ margin: '0 0 16px', fontSize: 12, fontWeight: 800, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px' }}>
                        Detalle por regla
                    </h4>
                    {Object.entries(reglas).map(([nombre, resultado]) => (
                        <BarraRegla key={nombre} nombre={nombre} resultado={resultado} />
                    ))}
                    <p style={{ margin: '4px 0 0', fontSize: 11.5, color: 'var(--text-4)', lineHeight: 1.5 }}>
                        Las reglas que la foto no permitía evaluar no cuentan en el score.
                    </p>
                </div>
            )}
        </div>
    );
}
