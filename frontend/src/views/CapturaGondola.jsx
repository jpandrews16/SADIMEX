import { useEffect, useRef, useState } from 'react';
import GondolaResultado from '../components/GondolaResultado.jsx';
import {
    API_URL, esperarAnalisis, hashArchivo, obtenerUbicacion,
    subirFoto, traerCategorias, traerSalas,
} from '../gondola.js';

/**
 * Captura de foto de góndola.
 *
 * Se usa de pie frente al mueble, con una mano, en un supermercado con mala
 * señal. Por eso: pocos campos, botones grandes, y el GPS se pide en
 * segundo plano sin bloquear nada.
 */

const CIUDAD_LABEL = { LPZ: 'La Paz', CBBA: 'Cochabamba', SCZ: 'Santa Cruz' };

const card = {
    background: 'var(--bg)', border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)', padding: 20, boxShadow: 'var(--shadow-sm)',
};

const label = {
    display: 'block', fontSize: 11.5, fontWeight: 800, color: 'var(--text-3)',
    textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 7,
};

const select = {
    width: '100%', boxSizing: 'border-box', background: 'var(--bg-2)',
    border: '1.5px solid var(--border)', borderRadius: 'var(--r)',
    padding: '13px 14px', fontSize: 15, color: 'var(--text-1)',
    outline: 'none', fontFamily: 'inherit', appearance: 'none',
};

/** Lo que el reponedor tiene que hacer para que la foto sirva. */
function Instrucciones() {
    return (
        <div style={{
            padding: '14px 16px', background: 'var(--blue-50)',
            border: '1px solid var(--blue-100)', borderRadius: 'var(--r)',
        }}>
            <div style={{ fontSize: 11.5, fontWeight: 800, color: 'var(--blue)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>
                Cómo tomar la foto
            </div>
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, color: 'var(--text-2)', lineHeight: 1.65 }}>
                <li><strong>Parate de frente al mueble</strong>, nunca en diagonal por el pasillo. Es lo que más falla: en diagonal las bandejas se van de fuga y el conteo sale mal.</li>
                <li><strong>El mueble completo</strong>, de piso a bandeja de arriba.</li>
                <li>Que se lean las <strong>etiquetas de precio</strong> del riel.</li>
                <li>Sin flash si hay reflejo en el vidrio.</li>
                <li>Si la góndola es muy larga, una foto por tramo.</li>
            </ul>
        </div>
    );
}

export default function CapturaGondola({ currentUser }) {
    const [salas, setSalas] = useState([]);
    const [categorias, setCategorias] = useState([]);
    const [salaId, setSalaId] = useState('');
    const [categoria, setCategoria] = useState('');

    const [archivo, setArchivo] = useState(null);
    const [preview, setPreview] = useState(null);
    const [ubicacion, setUbicacion] = useState(null);

    const [estado, setEstado] = useState('inicial'); // inicial | subiendo | analizando | listo | error
    const [mensaje, setMensaje] = useState('');
    const [alerta, setAlerta] = useState(null);
    const [analisis, setAnalisis] = useState(null);
    const [errorCarga, setErrorCarga] = useState('');

    const inputRef = useRef(null);

    /* Catálogo y salas de la ciudad del usuario */
    useEffect(() => {
        let vivo = true;
        (async () => {
            try {
                const [s, c] = await Promise.all([
                    traerSalas(currentUser?.ciudad),
                    traerCategorias(),
                ]);
                if (!vivo) return;
                setSalas(s);
                setCategorias(c);
                if (s.length === 1) setSalaId(s[0].id);
                if (c.length === 1) setCategoria(c[0]);
            } catch (err) {
                if (vivo) setErrorCarga(err.message || 'No se pudieron cargar las salas.');
            }
        })();
        return () => { vivo = false; };
    }, [currentUser?.ciudad]);

    /* El GPS se pide al abrir la pantalla: cuando el reponedor termina de
       elegir sala ya está resuelto y no hace esperar. */
    useEffect(() => {
        obtenerUbicacion().then(setUbicacion);
    }, []);

    useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

    const elegirArchivo = e => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (preview) URL.revokeObjectURL(preview);
        setArchivo(file);
        setPreview(URL.createObjectURL(file));
        setEstado('inicial');
        setMensaje('');
        setAnalisis(null);
        setAlerta(null);
    };

    const reiniciar = () => {
        if (preview) URL.revokeObjectURL(preview);
        setArchivo(null);
        setPreview(null);
        setAnalisis(null);
        setAlerta(null);
        setEstado('inicial');
        setMensaje('');
        if (inputRef.current) inputRef.current.value = '';
    };

    const enviar = async () => {
        if (!archivo || !salaId || !categoria) return;

        setEstado('subiendo');
        setMensaje('Subiendo la foto...');
        try {
            const sha256 = await hashArchivo(archivo);
            const { photoId, alerta: alertaCaptura } = await subirFoto({
                file: archivo,
                reponedorId: currentUser.id,
                salaId,
                categoria,
                ubicacion,
                sha256,
            });
            if (alertaCaptura) setAlerta(alertaCaptura);

            setEstado('analizando');
            setMensaje('Analizando la góndola...');
            const resultado = await esperarAnalisis(photoId, {
                onEstado: () => setMensaje('Analizando la góndola...'),
            });

            setAnalisis(resultado);
            setEstado('listo');
            setMensaje('');
        } catch (err) {
            setEstado('error');
            setMensaje(err.message || 'Algo falló al procesar la foto.');
        }
    };

    const trabajando = estado === 'subiendo' || estado === 'analizando';
    const listoParaEnviar = archivo && salaId && categoria && !trabajando;
    const salaElegida = salas.find(s => s.id === salaId);

    /* ── Resultado ──────────────────────────────────────────────── */
    if (estado === 'listo' && analisis) {
        return (
            <div style={{ maxWidth: 720, margin: '0 auto', padding: '28px 20px 60px' }}>
                <div style={{ marginBottom: 20 }}>
                    <h2 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 800, color: 'var(--text-1)' }}>
                        Resultado de la góndola
                    </h2>
                    <p style={{ margin: 0, fontSize: 13.5, color: 'var(--text-3)' }}>
                        {salaElegida?.cadenas?.nombre} · {salaElegida?.nombre} · {categoria}
                    </p>
                </div>

                {alerta && (
                    <div style={{
                        padding: '12px 14px', marginBottom: 16, background: 'var(--yellow-bg)',
                        border: '1px solid var(--yellow-border)', borderRadius: 'var(--r)',
                    }}>
                        <p style={{ margin: 0, fontSize: 12.5, fontWeight: 600, color: 'var(--yellow)' }}>
                            ⚠️ Sobre la captura: {alerta}
                        </p>
                    </div>
                )}

                <GondolaResultado analisis={analisis} />

                <button onClick={reiniciar} style={{
                    width: '100%', marginTop: 20, background: 'var(--blue)', color: '#fff',
                    border: 'none', borderRadius: 'var(--r)', padding: '15px 0',
                    fontSize: 15, fontWeight: 700, cursor: 'pointer', boxShadow: 'var(--shadow-blue)',
                }}>
                    📷 Tomar otra foto
                </button>
            </div>
        );
    }

    /* ── Formulario ─────────────────────────────────────────────── */
    return (
        <div style={{ maxWidth: 560, margin: '0 auto', padding: '28px 20px 60px' }}>
            <div style={{ marginBottom: 22 }}>
                <h2 style={{ margin: '0 0 4px', fontSize: 22, fontWeight: 800, color: 'var(--text-1)' }}>
                    🛒 Auditar góndola
                </h2>
                <p style={{ margin: 0, fontSize: 13.5, color: 'var(--text-3)' }}>
                    {CIUDAD_LABEL[currentUser?.ciudad] || currentUser?.ciudad} · {currentUser?.nombre}
                </p>
            </div>

            {!API_URL && (
                <div style={{
                    padding: '14px 16px', marginBottom: 16, background: 'var(--red-bg)',
                    border: '1px solid var(--red-border)', borderRadius: 'var(--r)',
                }}>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'var(--red)', lineHeight: 1.5 }}>
                        El módulo no está configurado: falta <code>VITE_GONDOLA_API_URL</code> con la URL
                        del servicio de góndola. Avisá al administrador.
                    </p>
                </div>
            )}

            {errorCarga && (
                <div style={{
                    padding: '14px 16px', marginBottom: 16, background: 'var(--red-bg)',
                    border: '1px solid var(--red-border)', borderRadius: 'var(--r)',
                }}>
                    <p style={{ margin: 0, fontSize: 13, fontWeight: 600, color: 'var(--red)' }}>{errorCarga}</p>
                </div>
            )}

            <div style={{ ...card, marginBottom: 16 }}>
                <div style={{ marginBottom: 18 }}>
                    <label style={label}>Sala</label>
                    <select value={salaId} onChange={e => setSalaId(e.target.value)} style={select}>
                        <option value="">Elegí la sala...</option>
                        {salas.map(s => (
                            <option key={s.id} value={s.id}>
                                {s.cadenas?.nombre ? `${s.cadenas.nombre} — ` : ''}{s.nombre}
                            </option>
                        ))}
                    </select>
                    {salas.length === 0 && !errorCarga && (
                        <p style={{ margin: '7px 0 0', fontSize: 12, color: 'var(--text-3)' }}>
                            No hay salas cargadas para tu ciudad todavía.
                        </p>
                    )}
                </div>

                <div>
                    <label style={label}>Categoría</label>
                    <select value={categoria} onChange={e => setCategoria(e.target.value)} style={select}>
                        <option value="">Elegí la categoría...</option>
                        {categorias.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    {categorias.length === 0 && !errorCarga && (
                        <p style={{ margin: '7px 0 0', fontSize: 12, color: 'var(--text-3)' }}>
                            No hay catálogo cargado todavía.
                        </p>
                    )}
                </div>
            </div>

            {/* Foto */}
            <div style={{ ...card, marginBottom: 16 }}>
                <label style={label}>Foto de la góndola</label>

                <input
                    ref={inputRef}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    onChange={elegirArchivo}
                    style={{ display: 'none' }}
                />

                {preview ? (
                    <div>
                        <img
                            src={preview}
                            alt="Góndola"
                            style={{
                                width: '100%', maxHeight: 340, objectFit: 'contain',
                                borderRadius: 'var(--r)', background: 'var(--bg-3)', display: 'block',
                            }}
                        />
                        <button
                            onClick={() => inputRef.current?.click()}
                            disabled={trabajando}
                            style={{
                                width: '100%', marginTop: 12, background: 'var(--bg-3)',
                                color: 'var(--text-2)', border: 'none', borderRadius: 'var(--r)',
                                padding: '11px 0', fontSize: 13.5, fontWeight: 700,
                                cursor: trabajando ? 'default' : 'pointer',
                            }}
                        >
                            Cambiar foto
                        </button>
                    </div>
                ) : (
                    <button
                        onClick={() => inputRef.current?.click()}
                        style={{
                            width: '100%', background: 'var(--bg-2)',
                            border: '2px dashed var(--border-hover)', borderRadius: 'var(--r)',
                            padding: '40px 20px', cursor: 'pointer', fontFamily: 'inherit',
                        }}
                    >
                        <div style={{ fontSize: 34, marginBottom: 8 }}>📷</div>
                        <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-1)', marginBottom: 3 }}>
                            Tomar foto
                        </div>
                        <div style={{ fontSize: 12.5, color: 'var(--text-3)' }}>
                            o elegir una de la galería
                        </div>
                    </button>
                )}

                <div style={{ marginTop: 12, fontSize: 12, color: ubicacion ? 'var(--green)' : 'var(--text-3)' }}>
                    {ubicacion
                        ? `📍 Ubicación tomada (±${Math.round(ubicacion.precision || 0)} m)`
                        : '📍 Sin ubicación — la foto se sube igual, pero queda marcada.'}
                </div>
            </div>

            <div style={{ marginBottom: 16 }}>
                <Instrucciones />
            </div>

            {mensaje && (
                <div style={{
                    padding: '13px 16px', marginBottom: 16,
                    background: estado === 'error' ? 'var(--red-bg)' : 'var(--blue-50)',
                    border: `1px solid ${estado === 'error' ? 'var(--red-border)' : 'var(--blue-100)'}`,
                    borderRadius: 'var(--r)',
                }}>
                    <p style={{
                        margin: 0, fontSize: 13, fontWeight: 600, lineHeight: 1.5,
                        color: estado === 'error' ? 'var(--red)' : 'var(--blue)',
                    }}>
                        {trabajando ? '⏳ ' : estado === 'error' ? '❌ ' : ''}{mensaje}
                    </p>
                </div>
            )}

            <button
                onClick={enviar}
                disabled={!listoParaEnviar}
                style={{
                    width: '100%', background: listoParaEnviar ? 'var(--blue)' : 'var(--bg-4)',
                    color: listoParaEnviar ? '#fff' : 'var(--text-4)',
                    border: 'none', borderRadius: 'var(--r)', padding: '16px 0',
                    fontSize: 15.5, fontWeight: 800, cursor: listoParaEnviar ? 'pointer' : 'default',
                    boxShadow: listoParaEnviar ? 'var(--shadow-blue)' : 'none',
                    transition: 'all var(--t)',
                }}
            >
                {trabajando ? 'Procesando...' : 'Analizar góndola'}
            </button>

            {estado === 'analizando' && (
                <p style={{ margin: '12px 0 0', fontSize: 12, color: 'var(--text-3)', textAlign: 'center', lineHeight: 1.5 }}>
                    Podés cerrar la pantalla: el análisis sigue y queda en tu historial.
                </p>
            )}
        </div>
    );
}
