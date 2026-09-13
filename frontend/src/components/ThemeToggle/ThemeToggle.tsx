import { SunIcon, MoonIcon, ComputerDesktopIcon } from '@heroicons/react/24/outline';
import { useTheme } from '../../contexts/ThemeContext';
import type { Theme } from '../../contexts/ThemeContext';
import './ThemeToggle.css';

const ORDER: Theme[] = ['light', 'dark', 'system'];
const LABELS: Record<Theme, string> = {
  light: 'Tema: Açık',
  dark: 'Tema: Koyu',
  system: 'Tema: Sistem',
};
const ICONS: Record<Theme, typeof SunIcon> = {
  light: SunIcon,
  dark: MoonIcon,
  system: ComputerDesktopIcon,
};

interface ThemeToggleProps {
  className?: string;
}

function ThemeToggle({ className = '' }: ThemeToggleProps) {
  const { theme, setTheme } = useTheme();
  const Icon = ICONS[theme];

  const handleClick = () => {
    const next = ORDER[(ORDER.indexOf(theme) + 1) % ORDER.length];
    setTheme(next);
  };

  return (
    <button
      type="button"
      className={`theme-toggle ${className}`.trim()}
      onClick={handleClick}
      title={LABELS[theme]}
      aria-label={LABELS[theme]}
    >
      <Icon />
    </button>
  );
}

export default ThemeToggle;
