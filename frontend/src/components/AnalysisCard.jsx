// Componente compartido para mostrar el análisis IA de una visita

const SENTIMENT = {
    positivo: { label: '😊 Positivo', color: '#16a34a', bg: '#dcfce7' },
    neutral:  { label: '🤔 Neutral',  color: '#b45309', bg: '#fef3c7' },
    frio:     { label: '😐 Frío',     color: '#dc2626', bg: '#fee2e2' },
};

const pill = (bg, color, text) => (
    <span style={{ fontSize: 11.5, fontWeight: 700, padding: '3px 9px', borderRadius: 99, background: bg, color, whiteSpace: 'nowrap' }}>
        {text}
    </span>
);

/** Versión compacta: solo las 2-3 pills clave. Ideal para filas de tabla. */
export function AnalysisPills({ a }) {
    if (!a) return null;
    const sent = SENTIMENT[a.sentimiento_cliente];
    return (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {pill(a.pedido_capturado ? '#dcfce7' : '#fee2e2', a.pedido_capturado ? '#16a34a' : '#dc2626', a.pedido_capturado ? '✅ Pedido' : '❌ Sin pedido')}
            {sent && pill(sent.bg, sent.color, sent.label)}
            {a.monto_aproximado && pill('#dcfce7', '#16a34a', `💰 ${a.monto_aproximado}`)}
        </div>
    );
}

/** Versión completa: resumen + pills + productos + quiebre + próximo paso. */
export function AnalysisDetail({ a }) {
    if (!a) return (
        <p style={{ margin: 0, color: 'var(--text-3)', fontSize: 12.5, fontStyle: 'italic' }}>
            Sin análisis IA — esta visita fue registrada antes de la función de análisis.
        </p>
    );

    const sent = SENTIMENT[a.sentimiento_cliente];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {a.resumen && (
                <p style={{ margin: 0, fontStyle: 'italic', color: 'var(--text-2)', fontSize: 13.5, lineHeight: 1.55 }}>
                    "{a.resumen}"
                </p>
            )}

            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {pill(a.pedido_capturado ? '#dcfce7' : '#fee2e2', a.pedido_capturado ? '#16a34a' : '#dc2626', a.pedido_capturado ? '✅ Pedido capturado' : '❌ Sin pedido')}
                {a.monto_aproximado && pill('#dcfce7', '#16a34a', `💰 ${a.monto_aproximado}`)}
                {sent && pill(sent.bg, sent.color, sent.label)}
            </div>

            {a.productos_mencionados?.length > 0 && (
                <div style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
                    <span style={{ color: 'var(--text-3)' }}>📦 Productos: </span>
                    {a.productos_mencionados.join(', ')}
                </div>
            )}

            {a.quiebre_stock?.length > 0 && (
                <div style={{ fontSize: 12.5, fontWeight: 600, color: '#dc2626' }}>
                    ⚠️ Quiebre de stock: {a.quiebre_stock.join(', ')}
                </div>
            )}

            {a.proximo_paso && (
                <div style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
                    <span style={{ color: 'var(--text-3)' }}>📌 Próximo paso: </span>
                    {a.proximo_paso}
                </div>
            )}
        </div>
    );
}
