import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import './SubTabs.css';

export interface SubTab<T extends string> {
  id: T;
  label: string;
}

interface SubTabsProps<T extends string> {
  /** Accessible name of the tab list, e.g. "RSS Beslemeleri bölümleri". */
  label: string;
  /** Prefix for the tab/panel element ids (unique per page). */
  idPrefix: string;
  tabs: SubTab<T>[];
  active: T;
  onChange: (id: T) => void;
  /** Content of the active tab. */
  children: ReactNode;
}

/**
 * Tabs inside a settings page: only the active section is rendered below the tab strip.
 * Keyboard follows the WAI-ARIA tabs pattern: only the active tab is in the Tab order, and
 * ←/→ (wrapping), Home and End move between tabs and activate them.
 */
function SubTabs<T extends string>({ label, idPrefix, tabs, active, onChange, children }: SubTabsProps<T>) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const handleKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const last = tabs.length - 1;
    const next =
      e.key === 'ArrowRight' ? (index === last ? 0 : index + 1)
      : e.key === 'ArrowLeft' ? (index === 0 ? last : index - 1)
      : e.key === 'Home' ? 0
      : e.key === 'End' ? last
      : null;
    if (next === null) return;
    e.preventDefault();
    onChange(tabs[next].id);
    tabRefs.current[next]?.focus();
  };

  return (
    <>
      <div className="sub-tabs" role="tablist" aria-label={label}>
        {tabs.map((tab, index) => (
          <button
            key={tab.id}
            ref={(el) => { tabRefs.current[index] = el; }}
            type="button"
            role="tab"
            id={`${idPrefix}-tab-${tab.id}`}
            aria-selected={tab.id === active}
            aria-controls={`${idPrefix}-panel`}
            tabIndex={tab.id === active ? 0 : -1}
            className={`sub-tab ${tab.id === active ? 'sub-tab-active' : ''}`}
            onClick={() => onChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div
        role="tabpanel"
        id={`${idPrefix}-panel`}
        aria-labelledby={`${idPrefix}-tab-${active}`}
        className="sub-tab-panel"
      >
        {children}
      </div>
    </>
  );
}

export default SubTabs;
