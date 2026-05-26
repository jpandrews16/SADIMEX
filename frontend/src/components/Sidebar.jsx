import { useState } from 'react';
import { supabase } from '../auth.js';

const nav = [
    { label: 'Usuarios',           icon: '👥', view: 'admin',      roles: ['admin'] },
    { label: 'Dashboard Nacional', icon: '📊', view: 'gerencia',   roles: ['admin', 'gerente'] },
    { label: 'Mi Equipo',          icon: '🧑‍💼', view: 'supervisor', roles: ['supervisor'] },
    { label: 'Mis Visitas',        icon: '📋', view: 'vendedor',   roles: ['vendedor'] },
    { label: 'Registrar Visita',   icon: '🎙️', view: 'upload',     roles: ['admin', 'gerente', 'supervisor', 'vendedor'] },
];

function ChangePasswordForm({ onClose }) {
    const [pwd, setPwd]       = useState('');
    const [confirm, setConfirm] = useState('');
    const [status, setStatus] = useState('');
    const [loading, setLoading] = useState(false);

    const handle = async e => {
        e.preventDefault();
        if (pwd.length < 6)     return setStatus('Mínimo 6 caracteres');
        if (pwd !== confirm)    return setStatus('Las contraseñas no coinciden');
        setLoading(true);
        const { error } = await supabase.auth.updateUser({ password: pwd });
        setLoading(false);
        if (error) return setStatus('Error: ' + error.message);
        setStatus('✅ Contraseña actualizada');
        setTimeout(onClose, 1600);
    };

    const inp = {
        width: '100%', boxSizing: 'border-box',
        background: 'var(--bg-2)', border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm)', padding: '8px 10px',
        color: 'var(--text-1)', fontSize: 13, outline: 'none', fontFamily: 'inherit',
    };

    return (
        <form onSubmit={handle} style={{ padding: '12px 14px', borderTop: '1px solid var(--border-2)', animation: 'fadeIn .15s' }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-3)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: 8 }}>
                🔑 Nueva contraseña
            </div>
            <input type="password" value={pwd} onChange={e => setPwd(e.target.value)}
                placeholder="Nueva contraseña" style={{ ...inp, marginBottom: 7 }} />
            <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)}
                placeholder="Confirmar contraseña" style={{ ...inp, marginBottom: 8 }} />
            {status && (
                <div style={{ fontSize: 12, color: status.startsWith('✅') ? 'var(--green)' : 'var(--red)', marginBottom: 8, fontWeight: 600 }}>
                    {status}
                </div>
            )}
            <div style={{ display: 'flex', gap: 6 }}>
                <button type="submit" disabled={loading} style={{
                    flex: 1, background: 'var(--blue)', color: '#fff', border: 'none',
                    borderRadius: 'var(--r-sm)', padding: '7px 0', fontSize: 12.5,
                    fontWeight: 700, cursor: 'pointer',
                }}>
                    {loading ? '...' : 'Guardar'}
                </button>
                <button type="button" onClick={onClose} style={{
                    background: 'var(--bg-3)', color: 'var(--text-3)', border: 'none',
                    borderRadius: 'var(--r-sm)', padding: '7px 10px', fontSize: 12.5,
                    fontWeight: 600, cursor: 'pointer',
                }}>
                    Cancelar
                </button>
            </div>
        </form>
    );
}

export default function Sidebar({ role, view, currentUser, onViewChange, onLogout }) {
    const [showChangePwd, setShowChangePwd] = useState(false);

    const defaultEmoji = { admin: '⚙️', gerente: '👔', supervisor: '📊', vendedor: '🧑‍💼' }[role] || '👤';
    const firstName    = currentUser?.nombre?.split(' ')[0] || 'Usuario';
    const lastName     = currentUser?.nombre?.split(' ')[1] || '';
    const shortName    = `${firstName} ${lastName}`.trim();

    return (
        <aside className="sidebar">
            {/* Logo */}
            <div style={{ padding: '12px 16px 8px', borderBottom: '1px solid var(--border-2)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <img src="/sadimex_icon.png" alt="" style={{ width: 40, height: 40, flexShrink: 0, borderRadius: 6 }} />
                    <span style={{ fontFamily: 'Inter, Arial, sans-serif', fontWeight: 900, fontSize: 20, color: '#0d1321', letterSpacing: '-0.5px', lineHeight: 1 }}>
                        SADIMEX
                    </span>
                </div>
                <div style={{ marginTop: 5, fontSize: 9, fontWeight: 700, color: 'var(--blue)', letterSpacing: '2px', textTransform: 'uppercase' }}>
                    Inteligencia de Ventas
                </div>
            </div>

            {/* Nav */}
            <nav className="sidebar-nav">
                <div className="nav-section-label">Módulos</div>
                {nav
                    .filter(n => n.roles.includes(role))
                    .map(n => (
                        <button
                            key={n.view}
                            className={`nav-link ${view === n.view ? 'active' : ''}`}
                            onClick={() => onViewChange(n.view)}
                        >
                            <span className="icon">{n.icon}</span>
                            {n.label}
                        </button>
                    ))
                }
            </nav>

            {/* Footer */}
            <div className="sidebar-footer" style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>

                {/* Cambiar contraseña (form inline) */}
                {showChangePwd && <ChangePasswordForm onClose={() => setShowChangePwd(false)} />}

                <button
                    style={{
                        display: 'flex', alignItems: 'center', gap: 8, width: '100%',
                        padding: '8px 12px', borderRadius: 'var(--r)', border: '1px solid transparent',
                        background: 'transparent', color: 'var(--text-3)', fontSize: 12, fontWeight: 600,
                        cursor: 'pointer', transition: 'all var(--t)',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.color = 'var(--text-2)'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-3)'; }}
                    onClick={() => setShowChangePwd(v => !v)}
                >
                    <span>🔑</span> Cambiar contraseña
                </button>

                <button
                    style={{
                        display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                        padding: '10px 12px', borderRadius: 'var(--r)', border: '1px solid transparent',
                        background: 'transparent', color: 'var(--text-3)', fontSize: 12.5, fontWeight: 600,
                        cursor: 'pointer', transition: 'all var(--t)',
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#fee2e2'; e.currentTarget.style.color = '#dc2626'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-3)'; }}
                    onClick={onLogout}
                >
                    <span style={{ fontSize: 16 }}>🚪</span> Cerrar Sesión
                </button>

                {/* User badge */}
                <div className="role-badge" style={{ marginTop: 4 }}>
                    <div className="avatar">
                        {currentUser?.avatar_url
                            ? <img src={currentUser.avatar_url} alt="" style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} />
                            : defaultEmoji}
                    </div>
                    <div>
                        <div className="name">{shortName}</div>
                        <div className="role-lbl">{role.charAt(0).toUpperCase() + role.slice(1)}</div>
                    </div>
                </div>
            </div>
        </aside>
    );
}
