import { Fragment, useState, type ReactNode } from 'react';
import { ChevronDownIcon, ChevronRightIcon, PencilIcon, TrashIcon, CheckIcon, XMarkIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import { useDeleteGroup, useGroups, useUpdateGroup } from '../../hooks/useApi';
import type { GroupKind } from '../../types';
import { GROUP_NAME_MAX_LENGTH, OTHER_GROUP_LABEL, groupErrorText, groupItems } from '../../utils/groupItems';
import './GroupedSettingsList.css';

interface GroupedSettingsListProps<T extends { id: number; group_id?: number | null }> {
  kind: GroupKind;
  /** Heading of the list, e.g. "Beslemeler". */
  title: string;
  /** Singular noun for the members, e.g. "besleme" ("2 besleme", "Bu grupta besleme yok"). */
  itemNoun: string;
  items: T[];
  isAdmin: boolean;
  renderItem: (item: T) => ReactNode;
  /** Toolbar buttons (e.g. "Yeni besleme ekle"). */
  actions?: ReactNode;
  /** Shown right under the toolbar (e.g. the open add form). */
  children?: ReactNode;
}

/**
 * Ayarlar list of feeds/topics shown under their groups (+ "Diğer"), with rename/delete on each
 * group header (admins only). Groups are created where a feed/topic is added (GroupSelect's
 * "+ Yeni grup…", Kategoriler › Düzenle), not here. Without any groups it is a plain list.
 */
function GroupedSettingsList<T extends { id: number; group_id?: number | null }>({
  kind, title, itemNoun, items, isAdmin, renderItem, actions, children,
}: GroupedSettingsListProps<T>) {
  const { data: groups = [] } = useGroups(kind);
  const { mutate: updateGroup, isPending: isUpdating } = useUpdateGroup();
  const { mutate: deleteGroup, isPending: isDeleting } = useDeleteGroup();
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [error, setError] = useState('');

  const handleRename = () => {
    if (editingId === null || !editName.trim()) return;
    setError('');
    updateGroup({ groupId: editingId, name: editName.trim() }, {
      onSuccess: () => setEditingId(null),
      onError: (err) => setError(groupErrorText(err, 'Grup güncellenirken hata oluştu.')),
    });
  };

  const handleDelete = (groupId: number, name: string) => {
    if (confirm(`"${name}" grubunu silmek istediğinizden emin misiniz? Üyeleri "${OTHER_GROUP_LABEL}" grubuna taşınacak.`)) {
      setError('');
      deleteGroup(groupId, {
        onError: (err) => setError(groupErrorText(err, 'Grup silinirken hata oluştu.')),
      });
    }
  };

  // Keyed here, so a caller's renderItem doesn't have to remember to set a key
  const renderItems = (list: T[]) => list.map(item => <Fragment key={item.id}>{renderItem(item)}</Fragment>);

  const toggleCollapsed = (key: string) =>
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });

  return (
    <section className="gsl" aria-label={title}>
      <div className="gsl-toolbar">
        <h3 className="gsl-title">
          {title} <span className="gsl-total">{items.length}</span>
        </h3>
        <div className="gsl-actions">{actions}</div>
      </div>

      {error && <p className="warning-text"><ExclamationTriangleIcon /> {error}</p>}

      {children}

      {groups.length === 0 ? (
        <div className="gsl-items">{renderItems(items)}</div>
      ) : (
        groupItems(items, groups, { includeEmpty: true }).map(section => {
          const isOpen = !collapsed.has(section.key);
          const group = section.group;
          return (
            <div key={section.key} className="gsl-group">
              {group && editingId === group.id ? (
                <div className="gsl-group-header gsl-inline-form">
                  <input
                    type="text"
                    className="topic-input"
                    aria-label="Grup adı"
                    maxLength={GROUP_NAME_MAX_LENGTH}
                    value={editName}
                    onChange={(e) => setEditName(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setEditingId(null); }}
                    disabled={isUpdating}
                    autoFocus
                  />
                  <button type="button" className="gsl-icon-button" onClick={handleRename} disabled={isUpdating || !editName.trim()} title="Kaydet">
                    <CheckIcon />
                  </button>
                  <button type="button" className="gsl-icon-button" onClick={() => setEditingId(null)} disabled={isUpdating} title="İptal">
                    <XMarkIcon />
                  </button>
                </div>
              ) : (
                <div className="gsl-group-header">
                  <button
                    type="button"
                    className="gsl-group-toggle"
                    onClick={() => toggleCollapsed(section.key)}
                    aria-expanded={isOpen}
                  >
                    {isOpen ? <ChevronDownIcon className="gsl-icon" /> : <ChevronRightIcon className="gsl-icon" />}
                    <span className="gsl-group-name">{section.label}</span>
                    <span className="gsl-group-count">· {section.items.length} {itemNoun}</span>
                  </button>
                  {isAdmin && group && (
                    <div className="gsl-group-actions">
                      <button
                        type="button"
                        className="gsl-icon-button"
                        onClick={() => { setError(''); setEditingId(group.id); setEditName(group.name); }}
                        title="Grubu yeniden adlandır"
                      >
                        <PencilIcon />
                      </button>
                      <button
                        type="button"
                        className="gsl-icon-button gsl-icon-button-danger"
                        onClick={() => handleDelete(group.id, group.name)}
                        disabled={isDeleting}
                        title="Grubu sil"
                      >
                        <TrashIcon />
                      </button>
                    </div>
                  )}
                </div>
              )}
              {isOpen && (
                section.items.length > 0
                  ? <div className="gsl-items">{renderItems(section.items)}</div>
                  : <p className="gsl-empty">Bu grupta {itemNoun} yok</p>
              )}
            </div>
          );
        })
      )}
    </section>
  );
}

export default GroupedSettingsList;
