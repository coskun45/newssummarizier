import { useEffect, useState } from 'react';
import { useCreateGroup, useGroups } from '../../hooks/useApi';
import type { GroupKind } from '../../types';
import { OTHER_GROUP_LABEL, GROUP_NAME_MAX_LENGTH, groupErrorText } from '../../utils/groupItems';
import './GroupSelect.css';

const NEW_GROUP = '__new__';

interface GroupSelectProps {
  kind: GroupKind;
  value: number | null;
  onChange: (groupId: number | null) => void;
  /** True while "+ Yeni grup…" is open but not created yet — the form must not save then, or the
   * typed group would be silently dropped. */
  onPendingChange?: (pending: boolean) => void;
  disabled?: boolean;
}

/** Group picker for the feed/topic add & edit forms. Empty = "Diğer"; "+ Yeni grup…" creates a
 * group in place and selects it. */
function GroupSelect({ kind, value, onChange, onPendingChange, disabled = false }: GroupSelectProps) {
  const { data: groups } = useGroups(kind);
  const { mutate: createGroup, isPending: isCreating } = useCreateGroup();
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    onPendingChange?.(creating);
  }, [creating, onPendingChange]);
  // Closing the form while a new group is open must not leave the parent blocked
  useEffect(() => () => onPendingChange?.(false), [onPendingChange]);

  const closeCreate = () => {
    setCreating(false);
    setNewName('');
    setError('');
  };

  const handleCreate = () => {
    if (!newName.trim()) return;
    setError('');
    createGroup({ kind, name: newName.trim() }, {
      onSuccess: (group) => {
        onChange(group.id);
        closeCreate();
      },
      onError: (err) => setError(groupErrorText(err, 'Grup oluşturulurken hata oluştu.')),
    });
  };

  return (
    <div className="group-select">
      <select
        className="topic-input"
        aria-label="Grup"
        value={creating ? NEW_GROUP : value ?? ''}
        onChange={(e) => {
          if (e.target.value === NEW_GROUP) {
            setCreating(true);
          } else {
            closeCreate();
            onChange(e.target.value === '' ? null : Number(e.target.value));
          }
        }}
        disabled={disabled}
      >
        <option value="">{OTHER_GROUP_LABEL}</option>
        {groups?.map(g => (
          <option key={g.id} value={g.id}>{g.name}</option>
        ))}
        <option value={NEW_GROUP}>+ Yeni grup…</option>
      </select>
      {creating && (
        <div className="group-select-new">
          <input
            type="text"
            className="topic-input"
            placeholder="Yeni grup adı"
            aria-label="Yeni grup adı"
            maxLength={GROUP_NAME_MAX_LENGTH}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); handleCreate(); } }}
            disabled={isCreating}
            autoFocus
          />
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={handleCreate}
            disabled={isCreating || !newName.trim()}
          >
            {isCreating ? 'Oluşturuluyor...' : 'Grubu oluştur'}
          </button>
          <button type="button" className="btn btn-secondary btn-sm" onClick={closeCreate} disabled={isCreating}>
            Vazgeç
          </button>
        </div>
      )}
      {error && <p className="warning-text">{error}</p>}
    </div>
  );
}

export default GroupSelect;
