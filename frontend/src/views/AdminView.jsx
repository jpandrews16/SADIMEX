import { useState, useEffect, useMemo, useCallback } from 'react';
import { supabase } from '../auth.js';

const CIUDADES = [
    { val: 'LPZ', label: '🏔️ La Paz' },
    { val: 'CBBA', label: '🌽 Cochabamba' },
    { val: 'SCZ', label: '🌴 Santa Cruz' },
    { val: 'NACIONAL', label: '🇧🇴 Nacional' },
];

const getCiudadIcon = (c) => {
    if (c === 'LPZ') return '🏔️';
    if (c === 'SCZ') return '🌴';
    if (c === 'CBBA') return '🌽';
    if (c === 'NACIONAL') return '🇧🇴';
    return '📍';
};

const ROLES = [
    { val: 'gerente', label: 'Gerente', desc: 'Acceso a dashboard nacional', icon: '👔' },
    { val: 'supervisor', label: 'Supervisor', desc: 'Gestión de equipo por ciudad', icon: '📊' },
    { val: 'vendedor', label: 'Vendedor', desc: 'Vista personal de visitas', icon: '🧑‍💼' },
];

const ROL_COLORS = {
    admin: { bg: '#f1f5f9', color: '#475569', badge: 'Super Admin' },
    gerente: { bg: '#ffedd5', color: '#c2410c', badge: 'Gerente' },
    supervisor: { bg: '#e0f2fe', color: '#0369a1', badge: 'Supervisor' },
    vendedor: { bg: '#f3e8ff', color: '#7e22ce', badge: 'Vendedor' },
};

const inputCls = {
    background: '#fff',
    border: '1px solid #e2e8f0', borderRadius: '8px',
    padding: '8px 14px', color: '#0f172a', fontSize: 13,
    outline: 'none', fontFamily: 'inherit',
};

export default function AdminView() {
    // ── All hooks declared first ──
    const [users, setUsers] = useState([]);
    const [filterRol, setFilterRol] = useState('all');
    const [filterCity, setFilterCity] = useState('all');
    const [searchTerm, setSearchTerm] = useState('');
    const [showForm, setShowForm] = useState(false);
    const [editingId, setEditingId] = useState(null);
    const [loading, setLoading] = useState(false);
    const [initLoading, setInitLoading] = useState(true);
    const [success, setSuccess] = useState('');
    const [error, setError] = useState('');
    const [form, setForm] = useState({ nombre: '', email: '', password: '', rol: 'vendedor', ciudad: 'LPZ', username: '', avatar_url: '' });

    useEffect(() => {
        const fetchUsers = async () => {
            try {
                const { data, error } = await supabase
                    .from('sadimex_profiles')
                    .select('*')
                    .order('created_at', { ascending: false });

                if (error) console.error("Error fetching Supabase users:", error);

                const dbUsers = (data || []).map(u => ({
                    ...u,
                    password: '•'.repeat(8)
                }));
                setUsers(dbUsers);
            } catch (err) {
                console.error(err);
                setUsers([]);
            } finally {
                setInitLoading(false);
            }
        };
        fetchUsers();
    }, []);

    const setF = k => e => setForm(p => ({ ...p, [k]: e.target.value }));

    // ── Memoized filtered list ──
    const filtered = useMemo(() => users.filter(u =>
        (filterRol === 'all' || u.rol === filterRol) &&
        (filterCity === 'all' || u.ciudad === filterCity) &&
        (searchTerm === '' ||
            (u.nombre && u.nombre.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (u.email && u.email.toLowerCase().includes(searchTerm.toLowerCase())) ||
            (u.username && u.username.toLowerCase().includes(searchTerm.toLowerCase())))
    ), [users, filterRol, filterCity, searchTerm]);

    // ── Memoized stats ──
    const stats = useMemo(() => ({
        total: users.length,
        activos: users.filter(u => u.activo).length,
        supervisores: users.filter(u => u.rol === 'supervisor').length,
        vendedores: users.filter(u => u.rol === 'vendedor').length,
    }), [users]);

    const handleEditClick = (u) => {
        setForm({ nombre: u.nombre, email: u.email, password: '', rol: u.rol, ciudad: u.ciudad, username: u.username || '', avatar_url: u.avatar_url || '' });
        setEditingId(u.id);
        setShowForm(true);
        window.scrollTo({ top: 0, behavior: 'smooth' });
    };

    const handleCreateOrUpdate = async e => {
        e.preventDefault();
        setError(''); setSuccess(''); setLoading(true);
        try {
            const un = form.username || form.email.split('@')[0];

            if (editingId && !String(editingId).startsWith('mock-')) {
                // UPDATE IN SUPABASE
                const { error: updateErr } = await supabase.from('sadimex_profiles').update({
                    nombre: form.nombre, rol: form.rol, ciudad: form.ciudad, username: un, avatar_url: form.avatar_url
                }).eq('id', editingId);

                if (updateErr) throw new Error(updateErr.message);

                setUsers(prev => prev.map(u => u.id === editingId ? { ...u, ...form, username: un } : u));
                setSuccess(`✅ Usuario "${form.nombre}" actualizado exitosamente.`);
            } else {
                // CREATE IN SUPABASE EDGE FUNCTION
                const { data, error: fnError } = await supabase.functions.invoke('create-sadimex-user', {
                    body: { ...form, username: un }
                });

                if (fnError || data?.error) throw new Error(fnError?.message || data?.error);

                const newUser = {
                    id: data.user?.id || Date.now(),
                    ...form,
                    username: un,
                    activo: true,
                    password: '•'.repeat(8)
                };
                setUsers(prev => [newUser, ...prev]);
                setSuccess(`✅ Usuario "${form.nombre}" creado exitosamente.`);
            }

            setForm({ nombre: '', email: '', password: '', rol: 'vendedor', ciudad: 'LPZ', username: '', avatar_url: '' });
            setShowForm(false);
            setEditingId(null);
        } catch (err) {
            setError(`Error: ${err.message}`);
        } finally {
            setLoading(false);
        }
    };

    // ── CRITICAL FIX: Persist activo toggle to Supabase ──
    const toggleActivo = useCallback(async (id) => {
        const user = users.find(u => u.id === id);
        if (!user) return;
        const newActivo = !user.activo;

        // Optimistic update
        setUsers(prev => prev.map(u => u.id === id ? { ...u, activo: newActivo } : u));

        const { error: updateErr } = await supabase
            .from('sadimex_profiles')
            .update({ activo: newActivo })
            .eq('id', id);

        if (updateErr) {
            // Rollback on failure
            console.error('Error toggling activo:', updateErr);
            setUsers(prev => prev.map(u => u.id === id ? { ...u, activo: !newActivo } : u));
            setError(`Error al cambiar estado: ${updateErr.message}`);
        } else {
            setSuccess(`✅ Usuario ${newActivo ? 'activado' : 'desactivado'} exitosamente.`);
        }
    }, [users]);

    return (
        <div className="animate-in" style={{ padding: '0 10px', maxWidth: 1200, margin: '0 auto', fontFamily: '"Inter", sans-serif' }}>
            {/* ── HEADER ── */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 24 }}>
                <div>
                    <h2 style={{ fontSize: 24, fontWeight: 800, color: '#0f172a', margin: '0 0 6px' }}>Gestión de Cuentas</h2>
                    <p style={{ fontSize: 13.5, color: '#64748b', margin: 0 }}>Administra tu equipo, roles y permisos de acceso</p>
                </div>
                <div style={{ display: 'flex', gap: 12 }}>
                    <button
                        style={{ ...inputCls, background: '#0f172a', color: '#fff', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', border: 'none' }}
                        onClick={() => { setShowForm(!showForm); setEditingId(null); setForm({ nombre: '', email: '', password: '', rol: 'vendedor', ciudad: 'LPZ', username: '', avatar_url: '' }); }}
                    >
                        {showForm ? '✕ Cancelar' : '👤 + Nuevo Usuario'}
                    </button>
                </div>
            </div>

            {/* ── KPI CARDS ── */}
            <div className="kpi-grid" style={{ gap: 15, marginBottom: 24 }}>
                {[
                    { label: 'Total Usuarios', val: stats.total, badge: `${stats.total} registrados`, color: '#10b981', bg: '#dcfce7', icon: '👥' },
                    { label: 'Usuarios Activos', val: stats.activos, badge: `${Math.round((stats.activos / (stats.total || 1)) * 100)}% activos`, color: '#10b981', bg: '#dcfce7', icon: '✨' },
                    { label: 'Supervisores', val: stats.supervisores, badge: 'Roles clave', color: '#6366f1', bg: '#e0e7ff', icon: '👔' },
                    { label: 'Vendedores', val: stats.vendedores, badge: 'Fuerza de venta', color: '#f59e0b', bg: '#fef3c7', icon: '🏃' },
                ].map(s => (
                    <div key={s.label} style={{
                        background: '#fff', borderRadius: 12, padding: '20px 24px',
                        border: '1px solid #e2e8f0', boxShadow: '0 1px 2px rgba(0,0,0,0.03)',
                        position: 'relative', overflow: 'hidden'
                    }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: '#64748b', marginBottom: 6 }}>{s.label}</div>
                        <div style={{ fontSize: 32, fontWeight: 800, color: '#0f172a' }}>{s.val}</div>
                        <div style={{
                            marginTop: 12, display: 'inline-block', background: s.bg, color: s.color,
                            padding: '3px 10px', borderRadius: 20, fontSize: 11.5, fontWeight: 700
                        }}>
                            {s.badge}
                        </div>
                        <div style={{ position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)', fontSize: 60, opacity: 0.04 }}>
                            {s.icon}
                        </div>
                    </div>
                ))}
            </div>

            {/* ── ALERTS ── */}
            {success && <div style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: 8, padding: '12px 18px', marginBottom: 16, fontSize: 13, color: '#15803d', fontWeight: 500 }}>{success}</div>}
            {error && <div style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: 8, padding: '12px 18px', marginBottom: 16, fontSize: 13, color: '#dc2626', fontWeight: 500 }}>{error}</div>}

            {/* ── CREATE USER FORM ── */}
            {showForm && (
                <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, padding: '24px', marginBottom: 24, boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)' }} className="animate-in">
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ background: editingId ? '#fef3c7' : '#e0e7ff', color: editingId ? '#d97706' : '#4f46e5', padding: '4px 8px', borderRadius: 6, fontSize: 12 }}>{editingId ? '✏️ Editar Registro' : '👤 Nuevo Registro'}</span>
                        {editingId ? 'Modificar datos del usuario' : 'Completar datos del perfil'}
                    </div>
                    <form onSubmit={handleCreateOrUpdate}>
                        <div className="grid-2" style={{ gap: 24 }}>
                            {/* Left col */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Nombre Completo *</label>
                                    <input value={form.nombre} onChange={setF('nombre')} required placeholder="Ej: Fernando Andrews" style={{ ...inputCls, width: '100%' }} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                                    <div>
                                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Email {editingId ? '(Bloqueado)' : '*'}</label>
                                        <input value={form.email} onChange={setF('email')} required={!editingId} disabled={!!editingId} type="email" placeholder="fandrews@sadimex.com" style={{ ...inputCls, width: '100%', opacity: editingId ? 0.6 : 1 }} />
                                    </div>
                                    <div>
                                        <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Nombre de usuario</label>
                                        <input value={form.username} onChange={setF('username')} placeholder="fandrews (opcional)" style={{ ...inputCls, width: '100%' }} />
                                    </div>
                                </div>
                                {!editingId && <div>
                                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Contraseña *</label>
                                    <input value={form.password} onChange={setF('password')} required placeholder="●●●●●●●●" style={{ ...inputCls, width: '100%' }} minLength={6} />
                                </div>}
                                <div>
                                    <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Foto de Perfil (URL Opcional)</label>
                                    <input value={form.avatar_url} onChange={setF('avatar_url')} placeholder="https://ejemplo.com/foto.jpg" style={{ ...inputCls, width: '100%' }} />
                                </div>
                            </div>

                            {/* Right col */}
                            <div>
                                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 8 }}>Rol Asignado *</label>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
                                    {ROLES.map(r => (
                                        <label key={r.val} style={{
                                            display: 'flex', alignItems: 'center', gap: 10, padding: '12px',
                                            borderRadius: 8, cursor: 'pointer',
                                            border: `1.5px solid ${form.rol === r.val ? '#0f172a' : '#e2e8f0'}`,
                                            background: form.rol === r.val ? '#f8fafc' : '#fff',
                                            transition: 'all 0.15s',
                                        }}>
                                            <input type="radio" name="rol" value={r.val} checked={form.rol === r.val} onChange={setF('rol')} style={{ display: 'none' }} />
                                            <div style={{ width: 14, height: 14, borderRadius: '50%', border: `4px solid ${form.rol === r.val ? '#0f172a' : '#cbd5e1'}`, flexShrink: 0 }} />
                                            <div style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{r.label}</div>
                                        </label>
                                    ))}
                                </div>

                                <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: '#475569', marginBottom: 6 }}>Sede / Ciudad *</label>
                                <select value={form.ciudad} onChange={setF('ciudad')} style={{ ...inputCls, width: '100%', cursor: 'pointer' }}>
                                    {CIUDADES.map(c => <option key={c.val} value={c.val}>{c.label}</option>)}
                                </select>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: 10, marginTop: 24, justifyContent: 'flex-end', paddingTop: 16, borderTop: '1px solid #e2e8f0' }}>
                            <button type="button" style={{ ...inputCls, background: '#fff', cursor: 'pointer', fontWeight: 600 }} onClick={() => { setShowForm(false); setEditingId(null); }}>Cancelar</button>
                            <button type="submit" style={{ ...inputCls, background: '#0f172a', color: '#fff', cursor: 'pointer', fontWeight: 600, border: 'none' }} disabled={loading}>
                                {loading ? 'Guardando...' : (editingId ? 'Guardar Cambios' : 'Guardar Nuevo Usuario')}
                            </button>
                        </div>
                    </form>
                </div>
            )}

            {/* ── TABLE CONTAINER ── */}
            <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 12, overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
                {/* ── Table Toolbar ── */}
                <div style={{ padding: '16px 20px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#f8fafc' }}>
                    <div style={{ position: 'relative', width: 280 }}>
                        <span style={{ position: 'absolute', left: 12, top: 9, fontSize: 14, color: '#94a3b8' }}>🔍</span>
                        <input value={searchTerm} onChange={e => setSearchTerm(e.target.value)} placeholder="Buscar por nombre, email o usuario..." style={{ ...inputCls, width: '100%', paddingLeft: 36 }} />
                    </div>
                    <div style={{ display: 'flex', gap: 10 }}>
                        <select value={filterRol} onChange={e => setFilterRol(e.target.value)} style={{ ...inputCls, cursor: 'pointer', background: '#fff' }}>
                            <option value="all">Rol: Todos</option>
                            {ROLES.map(r => <option key={r.val} value={r.val}>{r.label}</option>)}
                        </select>
                        <select value={filterCity} onChange={e => setFilterCity(e.target.value)} style={{ ...inputCls, cursor: 'pointer', background: '#fff' }}>
                            <option value="all">Ciudad: Todas</option>
                            {CIUDADES.map(c => <option key={c.val} value={c.val}>{c.label}</option>)}
                        </select>
                    </div>
                </div>

                {/* ── Table ── */}
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                        <thead>
                            <tr style={{ background: '#fff', borderBottom: '1px solid #e2e8f0' }}>
                                {['Usuario', 'Nombre de Usuario', 'Categoría', 'Región', 'Credenciales', 'Estado', 'Status App', 'Acciones'].map(h => (
                                    <th key={h} style={{ padding: '14px 20px', fontSize: 12, fontWeight: 700, color: '#64748b', whiteSpace: 'nowrap' }}>{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((u) => {
                                const rc = ROL_COLORS[u.rol] || ROL_COLORS.vendedor;

                                return (
                                    <tr key={u.id} style={{ borderBottom: '1px solid #f1f5f9', background: '#fff', transition: 'background 0.1s' }}
                                        onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                                        onMouseLeave={e => e.currentTarget.style.background = '#fff'}>

                                        {/* COL 1: Avatar, Name, Email */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                                                <div style={{ width: 40, height: 40, borderRadius: '50%', background: '#f1f5f9', border: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                                                    <img
                                                        src={u.avatar_url ? u.avatar_url : `https://api.dicebear.com/7.x/notionists/svg?seed=${u.username || u.nombre}&backgroundColor=transparent`}
                                                        alt=""
                                                        loading="lazy"
                                                        style={{ width: 40, height: 40, objectFit: 'cover' }}
                                                    />
                                                </div>
                                                <div>
                                                    <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>{u.nombre}</div>
                                                    <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{u.email}</div>
                                                </div>
                                            </div>
                                        </td>
                                        {/* COL 2: Username */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <span style={{ fontSize: 13, fontWeight: 600, color: '#334155', fontFamily: 'monospace' }}>@{u.username || u.email?.split('@')[0]}</span>
                                        </td>
                                        {/* COL 3: Role */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <span style={{ background: rc.bg, color: rc.color, borderRadius: 6, padding: '4px 8px', fontSize: 11.5, fontWeight: 700, whiteSpace: 'nowrap' }}>
                                                {rc.badge}
                                            </span>
                                        </td>
                                        {/* COL 4: Región */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <span style={{ fontSize: 12, color: '#64748b', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                                                <span>{getCiudadIcon(u.ciudad)}</span> {u.ciudad === 'NACIONAL' ? 'Nacional' : u.ciudad}
                                            </span>
                                        </td>
                                        {/* COL 5: Credentials */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <div style={{ fontSize: 12, color: '#334155', display: 'flex', flexDirection: 'column', gap: 4, fontFamily: 'monospace' }}>
                                                <strong style={{ fontWeight: 700, color: '#0f172a', fontFamily: 'inherit' }}>{u.username}</strong>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: 6, opacity: 0.9 }}>
                                                    <span style={{ fontSize: 11, background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, color: '#64748b' }}>🔒 Encriptada</span>
                                                </div>
                                            </div>
                                        </td>
                                        {/* COL 6: Estado */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <span style={{
                                                background: u.activo ? '#dcfce7' : '#fee2e2',
                                                color: u.activo ? '#166534' : '#991b1b',
                                                padding: '4px 10px', borderRadius: 4, fontSize: 12, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 6
                                            }}>
                                                <span style={{ width: 6, height: 6, borderRadius: '50%', background: u.activo ? '#16a34a' : '#ef4444' }} />
                                                {u.activo ? 'Activo' : 'Suspendido'}
                                            </span>
                                        </td>
                                        {/* COL 7: App Permissions */}
                                        <td style={{ padding: '16px 20px', fontSize: 12.5, color: '#475569', fontWeight: 500 }}>
                                            {u.activo ? 'Concedido' : 'Restringido'}
                                        </td>
                                        {/* COL 8: Actions */}
                                        <td style={{ padding: '16px 20px' }}>
                                            <div style={{ display: 'flex', gap: 8 }}>
                                                <button
                                                    onClick={() => toggleActivo(u.id)}
                                                    style={{
                                                        background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6,
                                                        padding: '6px 10px', fontSize: 12, fontWeight: 600, color: '#475569', cursor: 'pointer'
                                                    }}
                                                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                                                    onMouseLeave={e => e.currentTarget.style.background = '#fff'}
                                                >
                                                    {u.activo ? 'Desactivar 🛑' : 'Reactivar ✅'}
                                                </button>
                                                <button onClick={() => handleEditClick(u)} style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: 6, padding: '6px 10px', fontSize: 12, fontWeight: 600, color: '#475569', cursor: 'pointer' }}
                                                    onMouseEnter={e => e.currentTarget.style.background = '#f1f5f9'}
                                                    onMouseLeave={e => e.currentTarget.style.background = '#fff'}
                                                >
                                                    ✏️ Editar
                                                </button>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                            {filtered.length === 0 && (
                                <tr>
                                    <td colSpan={8} style={{ padding: '40px 20px', textAlign: 'center', color: '#64748b' }}>
                                        <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }}>🕵️‍♂️</div>
                                        No se encontraron usuarios con esos filtros.
                                    </td>
                                </tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>

            <div style={{ textAlign: 'center', fontSize: 12, color: '#94a3b8', marginTop: 24, paddingBottom: 40 }}>
                Administración de Usuarios Seguro - Sadimex Sales Intelligence
            </div>
        </div>
    );
}
