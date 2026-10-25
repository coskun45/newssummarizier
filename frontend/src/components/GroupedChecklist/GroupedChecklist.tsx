import { useEffect, useRef, useState } from 'react';
import { ChevronUpIcon, ChevronDownIcon } from '@heroicons/react/24/outline';
import type { ItemGroup } from '../../types';
import { groupItems } from '../../utils/groupItems';
import './GroupedChecklist.css';

export interface ChecklistItem {
  id: number;
  label: string;
  title?: string;
  count?: number;
  group_id?: number | null;
}

interface GroupedChecklistProps {
  items: ChecklistItem[];
  groups: ItemGroup[];
  selectedIds: number[];
  onToggle: (id: number) => void;
  onGroupToggle: (ids: number[], select: boolean) => void;
}

function ItemRow({ item, checked, onToggle }: { item: ChecklistItem; checked: boolean; onToggle: (id: number) => void }) {
  return (
    <label className="topic-item">
      <input type="checkbox" checked={checked} onChange={() => onToggle(item.id)} />
      <span className="topic-name" title={item.title}>{item.label}</span>
      {item.count !== undefined && <span className="topic-count">{item.count}</span>}
    </label>
  );
}

function GroupCheckbox({ label, checked, indeterminate, onChange }: {
  label: string;
  checked: boolean;
  indeterminate: boolean;
  onChange: () => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      aria-label={`${label} grubunun tümü`}
    />
  );
}

/** Sidebar checklist split into collapsible groups (+ "Diğer"). Without any groups it renders the
 * plain list, exactly like before grouping existed. */
function GroupedChecklist({ items, groups, selectedIds, onToggle, onGroupToggle }: GroupedChecklistProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  if (groups.length === 0) {
    return (
      <>
        {items.map(item => (
          <ItemRow key={item.id} item={item} checked={selectedIds.includes(item.id)} onToggle={onToggle} />
        ))}
      </>
    );
  }

  const toggleCollapsed = (key: string) =>
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  return (
    <>
      {groupItems(items, groups).map(section => {
        const ids = section.items.map(i => i.id);
        const selectedCount = ids.filter(id => selectedIds.includes(id)).length;
        const allSelected = selectedCount === ids.length;
        const isOpen = !collapsed.has(section.key);
        return (
          <div key={section.key} className="checklist-group">
            <div className="checklist-group-header">
              <GroupCheckbox
                label={section.label}
                checked={allSelected}
                indeterminate={selectedCount > 0 && !allSelected}
                onChange={() => onGroupToggle(ids, !allSelected)}
              />
              <button
                type="button"
                className="checklist-group-toggle"
                onClick={() => toggleCollapsed(section.key)}
                aria-expanded={isOpen}
              >
                <span className="checklist-group-name">{section.label}</span>
                <span className="topic-count">{ids.length}</span>
                <span className="importance-chevron">{isOpen ? <ChevronUpIcon /> : <ChevronDownIcon />}</span>
              </button>
            </div>
            {isOpen && (
              <div className="checklist-group-items">
                {section.items.map(item => (
                  <ItemRow key={item.id} item={item} checked={selectedIds.includes(item.id)} onToggle={onToggle} />
                ))}
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}

export default GroupedChecklist;
