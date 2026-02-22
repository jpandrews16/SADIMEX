const ROLES = {
    admin: { label: "Admin", emoji: "⚙️", defaultView: "admin" },
    gerente: { label: "Gerente Nacional", emoji: "👔", defaultView: "gerencia" },
    supervisor: { label: "Sup. La Paz", emoji: "📊", defaultView: "supervisor" },
    vendedor: { label: "Juan Mamani", emoji: "🧑‍💼", defaultView: "vendedor" },
};

const nav = [
    { label: "Usuarios", icon: "👥", view: "admin", roles: ["admin"] },
    { label: "Nacional", icon: "🏔️", view: "gerencia", roles: ["gerente"] },
    { label: "Mi Equipo", icon: "📋", view: "supervisor", roles: ["supervisor"] },
    { label: "Mis Visitas", icon: "📋", view: "vendedor", roles: ["vendedor"] },
    { label: "Subir Audio", icon: "🎙️", view: "upload", roles: ["admin", "gerente", "supervisor", "vendedor"] },
];

export default function Sidebar({ role, view, currentUser, onViewChange, onLogout }) {
    const defaultEmoji = role === 'admin' ? '⚙️' : role === 'gerente' ? '👔' : role === 'supervisor' ? '📊' : '🧑‍💼';
    const firstFirstName = currentUser?.nombre?.split(' ')[0] || "Usuario";
    const lastName = currentUser?.nombre?.split(' ')[1] || "";
    const shortName = `${firstFirstName} ${lastName}`.trim();

    return (
        <aside className="sidebar">
            {/* ── Logo: ícono real + SADIMEX texto ── */}
            <div style={{ padding: '12px 16px 8px', borderBottom: '1px solid var(--border-2)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <img
                        src="/sadimex_icon.png"
                        alt=""
                        style={{ width: 40, height: 40, flexShrink: 0, borderRadius: 6, display: 'block' }}
                    />
                    <span style={{
                        fontFamily: 'Inter, Arial, sans-serif',
                        fontWeight: 900,
                        fontSize: 20,
                        color: '#0d1321',
                        letterSpacing: '-0.5px',
                        lineHeight: 1,
                    }}>SADIMEX</span>
                </div>
                <div style={{ marginTop: 5, fontSize: 9, fontWeight: 700, color: 'var(--blue)', letterSpacing: '2px', textTransform: 'uppercase' }}>
                    Inteligencia de Ventas
                </div>
            </div>

            <nav className="sidebar-nav">
                <div className="nav-section-label">Módulos</div>
                {nav
                    .filter(n => n.roles.includes(role))
                    .map(n => (
                        <button
                            key={n.view}
                            className={`nav-link ${view === n.view ? "active" : ""}`}
                            onClick={() => onViewChange(n.view)}
                        >
                            <span className="icon">{n.icon}</span>
                            {n.label}
                        </button>
                    ))
                }
            </nav>

            {/* Footer with Logout and User badge */}
            <div className="sidebar-footer" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                <button
                    style={{
                        display: 'flex', alignItems: 'center', gap: '10px', width: '100%',
                        padding: '10px 12px', borderRadius: 'var(--r)', border: '1px solid transparent',
                        background: 'transparent', color: 'var(--text-3)', fontSize: '12.5px', fontWeight: 600,
                        cursor: 'pointer', transition: 'all var(--t)'
                    }}
                    onMouseEnter={e => { e.currentTarget.style.background = '#fee2e2'; e.currentTarget.style.color = '#dc2626'; }}
                    onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--text-3)'; }}
                    onClick={onLogout}
                >
                    <span style={{ fontSize: '16px' }}>🚪</span> Cerrar Sesión
                </button>
                <div className="role-badge">
                    <div className="avatar">
                        {currentUser?.avatar_url ? (
                            <img src={currentUser.avatar_url} alt="" style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} />
                        ) : defaultEmoji}
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
