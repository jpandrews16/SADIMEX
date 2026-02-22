import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar.jsx';
import GerenciaView from './views/GerenciaView.jsx';
import SupervisorView from './views/SupervisorView.jsx';
import VendedorView from './views/VendedorView.jsx';
import UploadAudio from './views/UploadAudio.jsx';
import AdminView from './views/AdminView.jsx';
import LoginPage from './views/LoginPage.jsx';
import { supabase, logout } from './auth.js';
import './index.css';

const VIEW_MAP = {
  admin: <AdminView />,
  gerencia: <GerenciaView />,
  supervisor: <SupervisorView />,
  vendedor: <VendedorView />,
  upload: <UploadAudio />,
};

const ROL_DEFAULT_VIEW = {
  admin: 'admin',
  gerente: 'gerencia',
  supervisor: 'supervisor',
  vendedor: 'vendedor',
};

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

  // ── App Shell ─────────────────────────────
  const activeView = view === 'admin'
    ? <AdminView currentUser={currentUser} />
    : VIEW_MAP[view] || <GerenciaView />;

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
        {activeView}
      </main>
    </div>
  );
}
