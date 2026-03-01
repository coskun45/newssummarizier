import { useState, FormEvent } from 'react';
import { authApi } from '../../services/api';
import type { AuthUser } from '../../types';
import './Login.css';

interface LoginProps {
    onLoginSuccess: (user: AuthUser) => void;
}

export default function Login({ onLoginSuccess }: LoginProps) {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setError('');
        setLoading(true);
        try {
            const response = await authApi.login(email, password);
            localStorage.setItem('auth_token', response.access_token);
            const authUser: AuthUser = {
                id: response.user.id,
                email: response.user.email,
                role: response.user.role as 'admin' | 'user',
            };
            localStorage.setItem('auth_user', JSON.stringify(authUser));
            onLoginSuccess(authUser);
        } catch (err: unknown) {
            const axiosErr = err as { response?: { data?: { detail?: string } } };
            setError(axiosErr.response?.data?.detail ?? 'Giriş başarısız. Lütfen tekrar deneyin.');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="login-page">
            <div className="login-card">
                <div className="login-header">
                    <h1>News Summarizer</h1>
                    <p>Lütfen giriş yapın</p>
                </div>
                <form className="login-form" onSubmit={handleSubmit}>
                    <div className="form-group">
                        <label htmlFor="email">E-Posta</label>
                        <input
                            id="email"
                            type="email"
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            placeholder="ornek@email.com"
                            required
                            autoFocus
                            autoComplete="email"
                        />
                    </div>
                    <div className="form-group">
                        <label htmlFor="password">Şifre</label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            placeholder="••••••••"
                            required
                            autoComplete="current-password"
                        />
                    </div>
                    {error && <div className="login-error">{error}</div>}
                    <button type="submit" className="login-btn" disabled={loading}>
                        {loading ? 'Giriş yapılıyor...' : 'Giriş Yap'}
                    </button>
                </form>
            </div>
        </div>
    );
}
