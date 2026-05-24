import { useState, useEffect, lazy, Suspense } from 'react';
import Sidebar from './components/Sidebar.jsx';
import LoginPage from './views/LoginPage.jsx';
import { supabase, logout } from './auth.js';
import './index.css';

// Lazy-load views — each user role only downloads the code they need
const GerenciaView = lazy(() => import('./views/GerenciaView.jsx'));
const SupervisorView = lazy(() => import('./views/SupervisorView.jsx'));
const VendedorView = lazy(() => import('./views/VendedorView.jsx'));
const UploadAudio = lazy(() => import('./views/UploadAudio.jsx'));
const AdminView = lazy(() => import('./views/AdminView.jsx'));

// Map view keys to component constructors (not instances)
const VIEW_COMPONENTS = {
  admin: AdminView,
  gerencia: GerenciaView,
  supervisor: SupervisorView,
  vendedor: VendedorView,
  upload: UploadAudio,
};

const ROL_DEFAULT_VIEW = {
  admin: 'admin',
  gerente: 'gerencia',
  supervisor: 'supervisor',
  vendedor: 'vendedor',
};

function LoadingFallback() {
  return (
    <div style={{
      display: 'flex', height: '60vh', alignItems: 'center', justifyContent: 'center',
      color: 'var(--text-3)', fontFamily: 'Inter', fontSize: 13, fontWeight: 600,
      letterSpacing: '1px', textTransform: 'uppercase',
    }}>
      ⏳ Cargando módulo...
    </div>
  );
}

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [view, setView] = useState('gerencia');
  const [loadingSession, setLoadingSession] = useState(true);

  useEffect(() => {
    // Restaurar sesión al recargar la página
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session?.user) {
        const { data: profile } = await supabase
          .from('sadimex_profiles')
          .select('*')
          .eq('id', session.user.id)
          .single();

        if (profile && profile.activo !== false) {
          setCurrentUser({ ...session.user, ...profile });
          setView(ROL_DEFAULT_VIEW[profile.rol] || 'gerencia');
        } else {
          await supabase.auth.signOut();
        }
      }
      setLoadingSession(false);
    });

    // Escuchar eventos de logout/login desde otras pestañas o componentes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT') {
        setCurrentUser(null);
        setView('gerencia');
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleLogout = async () => {
    await logout();
    setCurrentUser(null);
    setView('gerencia');
  };

  const handleViewChange = newView => setView(newView);

  // ── Loading Screen ─────────────────────────
  if (loadingSession) {
    return (
      <div style={{ display: 'flex', height: '100vh', alignItems: 'center', justifyContent: 'center', background: '#050A1E', color: '#fff', fontFamily: 'Inter' }}>
        <p style={{ fontWeight: 600, letterSpacing: '2px', textTransform: 'uppercase' }}>⚙️ Verificando Sesión...</p>
      </div>
    );
  }

  // ── Login ──────────────────────────────────
  if (!currentUser) {
    return <LoginPage onLogin={user => {
      setCurrentUser(user);
      setView(ROL_DEFAULT_VIEW[user.rol] || 'gerencia');
    }} />;
  }

  // ── Render active view dynamically ─────────
  const ActiveComponent = VIEW_COMPONENTS[view] || GerenciaView;
  const viewProps = (view === 'admin' || view === 'upload') ? { currentUser } : {};

  // ── App Shell ─────────────────────────────
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
          <ActiveComponent {...viewProps} />
        </Suspense>
      </main>
    </div>
  );
}
