import { RssIcon, FolderIcon, DocumentTextIcon, SparklesIcon, UsersIcon } from '@heroicons/react/24/outline';
import type { SettingsCategory } from './Settings';

interface SettingsNavProps {
  activeCategory: SettingsCategory;
  onCategoryChange: (category: SettingsCategory) => void;
  isAdmin: boolean;
}

const CATEGORIES: { id: SettingsCategory; label: string; Icon: typeof RssIcon }[] = [
  { id: 'feeds', label: 'RSS Beslemeleri', Icon: RssIcon },
  { id: 'topics', label: 'Kategoriler', Icon: FolderIcon },
  { id: 'summaryTypes', label: 'Özet Türleri', Icon: DocumentTextIcon },
  { id: 'prompts', label: 'Sistem Promptları', Icon: SparklesIcon },
];

function SettingsNav({ activeCategory, onCategoryChange, isAdmin }: SettingsNavProps) {
  const items = isAdmin
    ? [...CATEGORIES, { id: 'users' as const, label: 'Kullanıcı Yönetimi', Icon: UsersIcon }]
    : CATEGORIES;

  return (
    <nav className="settings-nav">
      {items.map(({ id, label, Icon }) => (
        <button
          key={id}
          className={`settings-nav-item${activeCategory === id ? ' settings-nav-item--active' : ''}`}
          onClick={() => onCategoryChange(id)}
        >
          <Icon className="settings-nav-icon" /> {label}
        </button>
      ))}
    </nav>
  );
}

export default SettingsNav;
