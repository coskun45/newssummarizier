import { useEffect, useRef, useState } from 'react';
import { ArrowRightStartOnRectangleIcon } from '@heroicons/react/24/outline';
import { useTheme } from '../../hooks/useTheme';
import { useAppInfo } from '../../hooks/useApi';
import type { Theme } from '../../contexts/theme-context';
import './UserMenu.css';

const THEME_LABELS: Record<Theme, string> = {
  light: 'Açık',
  dark: 'Koyu',
  system: 'Sistem',
};

interface UserMenuProps {
  email: string;
  onLogout: () => void;
}

function getInitials(email: string): string {
  const local = email.split('@')[0] || '';
  const parts = local.split(/[._\-+]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  if (parts.length === 1 && parts[0].length > 0) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return '?';
}

function UserMenu({ email, onLogout }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const { theme, setTheme } = useTheme();
  const { data: appInfo } = useAppInfo();

  useEffect(() => {
    if (!open) return;

    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };

    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  return (
    <div className="user-menu" ref={containerRef}>
      <button
        type="button"
        className="user-menu-avatar"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Kullanıcı menüsü: ${email}`}
        title={email}
      >
        {getInitials(email)}
      </button>

      {open && (
        <div className="user-menu-dropdown" role="menu">
          <div className="user-menu-email" title={email}>{email}</div>
          <div className="user-menu-divider" />
          <label className="user-menu-row">
            <span>Tema</span>
            <select
              className="select user-menu-theme-select"
              value={theme}
              onChange={(e) => setTheme(e.target.value as Theme)}
            >
              {(Object.keys(THEME_LABELS) as Theme[]).map((t) => (
                <option key={t} value={t}>{THEME_LABELS[t]}</option>
              ))}
            </select>
          </label>
          {appInfo?.version && (
            <div className="user-menu-row">
              <span>Sürüm</span>
              <span className="user-menu-version">v{appInfo.version}</span>
            </div>
          )}
          <div className="user-menu-divider" />
          <button type="button" className="user-menu-logout" onClick={onLogout}>
            <ArrowRightStartOnRectangleIcon /> Çıkış Yap
          </button>
        </div>
      )}
    </div>
  );
}

export default UserMenu;
