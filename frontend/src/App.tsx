import { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard/Dashboard';
import Login from './components/Login/Login';
import type { AuthUser } from './types';
import './App.css';

function App() {
    const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => {
        // Rehydrate from localStorage synchronously on first render (no login flash on refresh)
        const stored = localStorage.getItem('auth_user');
        return stored ? JSON.parse(stored) : null;
    });

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
            {currentUser === null
                ? <Login onLoginSuccess={handleLoginSuccess} />
                : <Dashboard currentUser={currentUser} onLogout={handleLogout} />
            }
        </div>
    );
}

export default App;
