import { XMarkIcon } from '@heroicons/react/24/outline';
import './SearchBar.css';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
}

function SearchBar({ value, onChange }: SearchBarProps) {
  return (
    <div className="search-bar">
      <input
        type="text"
        placeholder="Makalelerde ara..."
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="search-input"
      />
      {value && (
        <button
          className="search-clear"
          onClick={() => onChange('')}
          aria-label="Aramayı temizle"
        >
          <XMarkIcon />
        </button>
      )}
    </div>
  );
}

export default SearchBar;
