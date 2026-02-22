import { useState } from 'react';
import { authenticate } from '../auth.js';

export default function LoginPage({ onLogin }) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPass, setShowPass] = useState(false);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState('');

    const handleSubmit = async e => {
        e.preventDefault();
        setError('');
        if (!username.trim() || !password) { setError('Completa todos los campos'); return; }
        setLoading(true);
        // await new Promise(r => setTimeout(r, 800)); // Remove fake delay if desirable, but leaving for now is fine
        const result = await authenticate(username, password);
        setLoading(false);
        if (result.success) {
            onLogin(result.user);
        } else {
            setError(result.error || 'Error desconocido');
        }
    };

    return (
        <div style={{
            position: 'fixed', inset: 0,
            backgroundImage: 'url(/bolivia_bg.png)',
            backgroundSize: 'cover', backgroundPosition: 'center',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '0 6vw',
            fontFamily: "'Inter', 'Segoe UI', sans-serif",
        }}>
            {/* Dark overlay */}
            <div style={{
                position: 'absolute', inset: 0,
                background: 'linear-gradient(120deg, rgba(5,10,30,0.72) 0%, rgba(5,10,30,0.45) 50%, rgba(5,10,30,0.60) 100%)',
                backdropFilter: 'blur(0px)',
            }} />

            {/* ── LEFT: Brand copy ──────────────────────────────── */}
            <div style={{ position: 'relative', zIndex: 1, color: '#fff', maxWidth: 480, flex: '0 0 auto' }}>
                {/* Logo row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 40 }}>
                    <img src="/sadimex_icon.png" alt="SADIMEX" style={{ width: 52, height: 52, borderRadius: 10 }} />
                    <span style={{ fontWeight: 900, fontSize: 22, letterSpacing: '-0.3px', color: '#fff' }}>SADIMEX</span>
                </div>

                <h1 style={{
                    fontSize: 'clamp(40px, 6vw, 72px)',
                    fontWeight: 900,
                    lineHeight: 1.0,
                    margin: '0 0 20px',
                    letterSpacing: '-2px',
                    textTransform: 'uppercase',
                    textShadow: '0 2px 24px rgba(0,0,0,0.4)',
                }}>
                    INTELIGENCIA<br />COMERCIAL
                </h1>

                <p style={{ fontSize: 16, color: 'rgba(255,255,255,0.80)', maxWidth: 340, lineHeight: 1.65, marginBottom: 12 }}>
                    Análisis de visitas de ventas en tiempo real.<br />
                    Potenciado por IA para equipos en campo.
                </p>

                {/* City tags */}
                <div style={{ display: 'flex', gap: 10, marginTop: 28 }}>
                    {['🏔️ La Paz', '🌿 Cochabamba', '🌴 Santa Cruz'].map(c => (
                        <span key={c} style={{
                            background: 'rgba(255,255,255,0.15)',
                            backdropFilter: 'blur(8px)',
                            border: '1px solid rgba(255,255,255,0.25)',
                            borderRadius: 20, padding: '5px 14px', fontSize: 12.5,
                            color: '#fff', fontWeight: 600,
                        }}>{c}</span>
                    ))}
                </div>
            </div>

            {/* ── RIGHT: Glassmorphic Login Card ────────────────── */}
            <div style={{
                position: 'relative', zIndex: 1,
                background: 'rgba(255,255,255,0.13)',
                backdropFilter: 'blur(22px)',
                WebkitBackdropFilter: 'blur(22px)',
                border: '1px solid rgba(255,255,255,0.28)',
                borderRadius: 24,
                padding: '40px 40px 36px',
                width: '100%', maxWidth: 400,
                boxShadow: '0 8px 60px rgba(0,0,0,0.35)',
                flexShrink: 0,
            }}>
                <h2 style={{ color: '#fff', fontWeight: 800, fontSize: 22, margin: '0 0 6px', letterSpacing: '-0.3px' }}>
                    Iniciar Sesión
                </h2>
                <p style={{ color: 'rgba(255,255,255,0.65)', fontSize: 13.5, margin: '0 0 28px' }}>
                    Ingresa con tu nombre de usuario
                </p>

                <form onSubmit={handleSubmit}>
                    {/* Username */}
                    <div style={{ marginBottom: 16 }}>
                        <label style={{ display: 'block', color: 'rgba(255,255,255,0.75)', fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: 7 }}>
                            Usuario
                        </label>
                        <input
                            value={username}
                            onChange={e => setUsername(e.target.value)}
                            placeholder="ej: jpandrews"
                            autoComplete="username"
                            style={{
                                width: '100%', boxSizing: 'border-box',
                                background: 'rgba(255,255,255,0.92)',
                                border: '1.5px solid rgba(255,255,255,0.4)',
                                borderRadius: 12, padding: '12px 14px',
                                fontSize: 14, color: '#0d1321', outline: 'none',
                                fontFamily: 'inherit',
                                transition: 'border-color 0.2s',
                            }}
                            onFocus={e => e.target.style.borderColor = '#3B82F6'}
                            onBlur={e => e.target.style.borderColor = 'rgba(255,255,255,0.4)'}
                        />
                    </div>

                    {/* Password */}
                    <div style={{ marginBottom: 10 }}>
                        <label style={{ display: 'block', color: 'rgba(255,255,255,0.75)', fontSize: 11.5, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '1.2px', marginBottom: 7 }}>
                            Contraseña
                        </label>
                        <div style={{ position: 'relative' }}>
                            <input
                                value={password}
                                onChange={e => setPassword(e.target.value)}
                                type={showPass ? 'text' : 'password'}
                                placeholder="••••••••"
                                autoComplete="current-password"
                                style={{
                                    width: '100%', boxSizing: 'border-box',
                                    background: 'rgba(255,255,255,0.92)',
                                    border: '1.5px solid rgba(255,255,255,0.4)',
                                    borderRadius: 12, padding: '12px 42px 12px 14px',
                                    fontSize: 14, color: '#0d1321', outline: 'none',
                                    fontFamily: 'inherit',
                                    transition: 'border-color 0.2s',
                                }}
                                onFocus={e => e.target.style.borderColor = '#3B82F6'}
                                onBlur={e => e.target.style.borderColor = 'rgba(255,255,255,0.4)'}
                            />
                            <button type="button" onClick={() => setShowPass(!showPass)} style={{
                                position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
                                background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: '#666',
                            }}>
                                {showPass ? '🙈' : '👁️'}
                            </button>
                        </div>
                    </div>

                    {/* Error */}
                    {error && (
                        <div style={{
                            background: 'rgba(239,68,68,0.18)', border: '1px solid rgba(239,68,68,0.4)',
                            borderRadius: 10, padding: '9px 14px', marginBottom: 14,
                            color: '#fca5a5', fontSize: 13, fontWeight: 600,
                        }}>
                            ⚠️ {error}
                        </div>
                    )}

                    {/* Submit */}
                    <button type="submit" disabled={loading} style={{
                        width: '100%', marginTop: 18,
                        background: loading
                            ? 'rgba(59,130,246,0.6)'
                            : 'linear-gradient(135deg, #2563EB 0%, #1d4ed8 100%)',
                        color: '#fff', border: 'none', borderRadius: 12,
                        padding: '13px 0', fontSize: 15, fontWeight: 800,
                        cursor: loading ? 'not-allowed' : 'pointer',
                        letterSpacing: '0.3px',
                        boxShadow: '0 4px 20px rgba(37,99,235,0.4)',
                        transition: 'all 0.18s',
                    }}
                        onMouseEnter={e => { if (!loading) e.target.style.transform = 'translateY(-1px)'; }}
                        onMouseLeave={e => { e.target.style.transform = 'none'; }}
                    >
                        {loading ? '⚙️ Verificando...' : 'INGRESAR →'}
                    </button>
                </form>

                {/* Footer hint */}
                <p style={{ textAlign: 'center', marginTop: 22, color: 'rgba(255,255,255,0.45)', fontSize: 12 }}>
                    Sadimex Sales Intelligence · Bolivia 🇧🇴
                </p>
            </div>
        </div>
    );
}
