import { useState, useEffect, lazy, Suspense } from 'react';
import Sidebar from './components/Sidebar.jsx';
import LoginPage from './views/LoginPage.jsx';
import { supabase, logout } from './auth.js';
import './index.css';

const GerenciaView  = lazy(() => import('./views/GerenciaView.jsx'));
const SupervisorView = lazy(() => import('./views/SupervisorView.jsx'));
const VendedorView  = lazy(() => import('./views/VendedorView.jsx'));
const UploadAudio   = lazy(() => import('./views/UploadAudio.jsx'));
const AdminView     = lazy(() => import('./views/AdminView.jsx'));
const CapturaGondola   = lazy(() => import('./views/CapturaGondola.jsx'));
const GondolaDashboard = lazy(() => import('./views/GondolaDashboard.jsx'));

const VIEW_COMPONENTS = {
  admin: AdminView, gerencia: GerenciaView,
  supervisor: SupervisorView, vendedor: VendedorView, upload: UploadAudio,
  'gondola-captura': CapturaGondola, 'gondola-dashboard': GondolaDashboard,
};
const ROL_DEFAULT_VIEW = {
  admin: 'admin', gerente: 'gerencia', supervisor: 'supervisor', vendedor: 'vendedor',
  // El reponedor entra directo a capturar: es lo único que hace en la app.
  reponedor: 'gondola-captura',
};

function LoadingFallback() {
  return (
    <div style={{ display: 'flex', height: '60vh', alignItems: 'center', justifyContent: 'center', color: 'var(--text-3)', fontFamily: 'Inter', fontSize: 13, fontWeight: 600, letterSpacing: '1px', textTransform: 'uppercase' }}>
      ⏳ Cargando módulo...
    </div>
  );
}

/** Modal para cambiar contraseña cuando el usuario vuelve desde un link de recuperación */
function RecoveryModal({ onDone }) {
  const [pwd, setPwd]         = useState('');
  const [confirm, setConfirm] = useState('');
  const [status, setStatus]   = useState('');
  const [loading, setLoading] = useState(false);

  const handle = async e => {
    e.preventDefault();
    if (pwd.length < 6)  return setStatus('Mínimo 6 caracteres');
    if (pwd !== confirm) return setStatus('Las contraseñas no coinciden');
    setLoading(true);
    const { error } = await supabase.auth.updateUser({ password: pwd });
    setLoading(false);
    if (error) return setStatus('Error: ' + error.message);
    setStatus('✅ Contraseña actualizada. Ingresando...');
    setTimeout(onDone, 1500);
  };

  const inp = {
    width: '100%', boxSizing: 'border-box', marginBottom: 12,
    background: '#f8fafc', border: '1.5px solid #e2e8f0', borderRadius: 10,
    padding: '11px 14px', fontSize: 14, color: '#0f172a', outline: 'none', fontFamily: 'inherit',
  };

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999 }}>
      <div style={{ background: '#fff', borderRadius: 16, padding: '32px 28px', width: '100%', maxWidth: 380, boxShadow: '0 20px 60px rgba(0,0,0,0.25)' }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 18, fontWeight: 800, color: '#0f172a' }}>🔑 Nueva contraseña</h3>
        <p style={{ margin: '0 0 24px', fontSize: 13, color: '#64748b' }}>Elegí una nueva contraseña para tu cuenta.</p>
        <form onSubmit={handle}>
          <input type="password" value={pwd} onChange={e => setPwd(e.target.value)} placeholder="Nueva contraseña" style={inp} />
          <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} placeholder="Confirmar contraseña" style={{ ...inp, marginBottom: 16 }} />
          {status && <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: status.startsWith('✅') ? '#16a34a' : '#dc2626' }}>{status}</p>}
          <button type="submit" disabled={loading} style={{ width: '100%', background: '#0f172a', color: '#fff', border: 'none', borderRadius: 10, padding: '13px 0', fontSize: 14, fontWeight: 700, cursor: 'pointer' }}>
            {loading ? 'Guardando...' : 'Guardar contraseña'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default function App() {
  const [currentUser, setCurrentUser]     = useState(null);
  const [view, setView]                   = useState('gerencia');
  const [loadingSession, setLoadingSession] = useState(true);
  const [recoveryMode, setRecoveryMode]   = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session?.user) {
        const { data: profile } = await supabase
          .from('sadimex_profiles').select('*').eq('id', session.user.id).single();
        if (profile && profile.activo !== false) {
          setCurrentUser({ ...session.user, ...profile });
          setView(ROL_DEFAULT_VIEW[profile.rol] || 'gerencia');
        } else {
          await supabase.auth.signOut();
        }
      }
      setLoadingSession(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        setCurrentUser(null);
        setView('gerencia');
        setRecoveryMode(false);
      }
      if (event === 'PASSWORD_RECOVERY') {
        // El usuario llegó desde un link de recuperación — mostrar modal
        setRecoveryMode(true);
        setLoadingSession(false);
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleLogout = async () => { await logout(); setCurrentUser(null); setView('gerencia'); };
  const handleViewChange = newView => setView(newView);

  if (loadingSession) return (
    <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', background: '#050A1E', color: '#fff', fontFamily: 'Inter' }}>
      <p style={{ fontWeight: 600, letterSpacing: '2px', textTransform: 'uppercase' }}>⚙️ Verificando Sesión...</p>
    </div>
  );

  // Modal de recuperación de contraseña (viene del link de email)
  if (recoveryMode) return (
    <RecoveryModal onDone={() => {
      setRecoveryMode(false);
      // Recargar para restaurar sesión limpia
      window.location.reload();
    }} />
  );

  if (!currentUser) return (
    <LoginPage onLogin={user => {
      setCurrentUser(user);
      setView(ROL_DEFAULT_VIEW[user.rol] || 'gerencia');
    }} />
  );

  const ActiveComponent = VIEW_COMPONENTS[view] || GerenciaView;

  return (
    <div className="app-shell">
      <Sidebar
        role={currentUser.rol}
        view={view}
        currentUser={currentUser}
        onViewChange={handleViewChange}
        onLogout={handleLogout}
      />
      <main className="main-content">
        <Suspense fallback={<LoadingFallback />}>
          <ActiveComponent currentUser={currentUser} />
        </Suspense>
      </main>
    </div>
  );
}
