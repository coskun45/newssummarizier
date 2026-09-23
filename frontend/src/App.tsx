import { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard/Dashboard';
import Login from './components/Login/Login';
import ToastContainer from './components/Toast/ToastContainer';
import { authApi, saveSession } from './services/api';
import type { AuthUser } from './types';
import './App.css';

function App() {
    const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => {
        // Rehydrate from localStorage synchronously on first render (no login flash on refresh)
        const stored = localStorage.getItem('auth_user');
        return stored ? JSON.parse(stored) : null;
    });

    // Local dev auto-login: with no stored session, ask the backend for a dev token once.
    // It answers 404 unless DEV_AUTO_LOGIN + DEBUG are set, and we fall back to <Login/>.
    const [checkingDevLogin, setCheckingDevLogin] = useState(currentUser === null);
    useEffect(() => {
        if (!checkingDevLogin) return;
        let cancelled = false;
        authApi.devLogin()
            .then((response) => { if (!cancelled) setCurrentUser(saveSession(response)); })
            .catch(() => { /* not enabled — show the login page */ })
            .finally(() => { if (!cancelled) setCheckingDevLogin(false); });
        return () => { cancelled = true; };
    }, [checkingDevLogin]);

    // Listen for 401 logout events dispatched by the axios response interceptor
    useEffect(() => {
        const handle = () => setCurrentUser(null);
        window.addEventListener('auth:logout', handle);
        return () => window.removeEventListener('auth:logout', handle);
    }, []);

    const handleLogout = () => {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('auth_user');
        setCurrentUser(null);
    };

    const handleLoginSuccess = (user: AuthUser) => {
        setCurrentUser(user);
    };

    return (
        <div className="App">
            {checkingDevLogin
                ? null
                : currentUser === null
                ? <Login onLoginSuccess={handleLoginSuccess} />
                : <Dashboard currentUser={currentUser} onLogout={handleLogout} />
            }
            <ToastContainer />
        </div>
    );
}

export default App;
