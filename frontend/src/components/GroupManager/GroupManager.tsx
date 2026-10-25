import { useState } from 'react';
import { PencilIcon, TrashIcon, CheckIcon, XMarkIcon, PlusIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import { useCreateGroup, useDeleteGroup, useGroups, useUpdateGroup } from '../../hooks/useApi';
import type { GroupKind } from '../../types';
import { OTHER_GROUP_LABEL, GROUP_NAME_MAX_LENGTH, groupErrorText as errorText } from '../../utils/groupItems';
import './GroupManager.css';

interface GroupManagerProps {
  kind: GroupKind;
  isAdmin: boolean;
  /** Members per group id, shown next to the name. */
  memberCounts?: Record<number, number>;
}

/** CRUD for the sidebar groups of feeds or topics (Ayarlar › RSS Beslemeleri / Kategoriler). */
function GroupManager({ kind, isAdmin, memberCounts = {} }: GroupManagerProps) {
  const { data: groups } = useGroups(kind);
  const { mutate: createGroup, isPending: isCreating } = useCreateGroup();
  const { mutate: updateGroup, isPending: isUpdating } = useUpdateGroup();
  const { mutate: deleteGroup, isPending: isDeleting } = useDeleteGroup();
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState('');
  const [error, setError] = useState('');

  const handleCreate = () => {
    if (!newName.trim()) return;
    setError('');
    createGroup({ kind, name: newName.trim() }, {
      onSuccess: () => setNewName(''),
      onError: (err) => setError(errorText(err, 'Grup oluşturulurken hata oluştu.')),
    });
  };

  const handleSave = () => {
    if (editingId === null || !editName.trim()) return;
    setError('');
    updateGroup({ groupId: editingId, name: editName.trim() }, {
      onSuccess: () => setEditingId(null),
      onError: (err) => setError(errorText(err, 'Grup güncellenirken hata oluştu.')),
    });
  };

  const handleDelete = (groupId: number, name: string) => {
    if (confirm(`"${name}" grubunu silmek istediğinizden emin misiniz? Üyeleri "${OTHER_GROUP_LABEL}" grubuna taşınacak.`)) {
      setError('');
      deleteGroup(groupId, {
        onError: (err) => setError(errorText(err, 'Grup silinirken hata oluştu.')),
      });
    }
  };

  return (
    <section className="group-manager" aria-label="Gruplar">
      <h3 className="group-manager-title">Gruplar</h3>
      <p className="section-description">
        Sol paneldeki listeyi gruplar. Grubu olmayanlar "{OTHER_GROUP_LABEL}" altında görünür.
      </p>
      <div className="user-list">
        {groups?.map(group => (
          editingId === group.id ? (
            <div key={group.id} className="user-list-item">
              <input
                type="text"
                className="topic-input group-manager-input"
                aria-label="Grup adı"
                maxLength={GROUP_NAME_MAX_LENGTH}
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
                disabled={isUpdating}
                autoFocus
              />
              <div className="topic-actions">
                <button className="edit-topic-button" onClick={() => setEditingId(null)} disabled={isUpdating} title="İptal">
                  <XMarkIcon />
                </button>
                <button className="edit-topic-button" onClick={handleSave} disabled={isUpdating || !editName.trim()} title="Kaydet">
                  <CheckIcon />
                </button>
              </div>
            </div>
          ) : (
            <div key={group.id} className="user-list-item">
              <div className="user-list-info">
                <span className="user-list-email">{group.name}</span>
                <span className="user-role-badge">{memberCounts[group.id] ?? 0}</span>
              </div>
              {isAdmin && (
                <div className="topic-actions">
                  <button
                    className="edit-topic-button"
                    onClick={() => { setError(''); setEditingId(group.id); setEditName(group.name); }}
                    title="Grubu yeniden adlandır"
                  >
                    <PencilIcon />
                  </button>
                  <button
                    className="delete-topic-button"
                    onClick={() => handleDelete(group.id, group.name)}
                    disabled={isDeleting}
                    title="Grubu sil"
                  >
                    <TrashIcon />
                  </button>
                </div>
              )}
            </div>
          )
        ))}
        {groups?.length === 0 && <p className="section-description">Henüz grup yok.</p>}
      </div>
      {isAdmin && (
        <div className="group-manager-add">
          <input
            type="text"
            className="topic-input group-manager-input"
            placeholder="Yeni grup adı (ör. Avrupa)"
            aria-label="Yeni grup adı"
            maxLength={GROUP_NAME_MAX_LENGTH}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
            disabled={isCreating}
          />
          <button className="btn btn-secondary btn-sm" onClick={handleCreate} disabled={isCreating || !newName.trim()}>
            <PlusIcon className="group-manager-icon" /> {isCreating ? 'Ekleniyor...' : 'Grup ekle'}
          </button>
        </div>
      )}
      {error && <p className="warning-text"><ExclamationTriangleIcon /> {error}</p>}
    </section>
  );
}

export default GroupManager;
