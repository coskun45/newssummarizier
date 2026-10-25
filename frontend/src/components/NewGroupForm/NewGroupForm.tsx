import { useState } from 'react';
import { ExclamationTriangleIcon, CheckIcon } from '@heroicons/react/24/outline';
import { useCreateGroup } from '../../hooks/useApi';
import type { GroupKind } from '../../types';
import { GROUP_NAME_MAX_LENGTH, groupErrorText } from '../../utils/groupItems';
import './NewGroupForm.css';

interface NewGroupFormProps {
  kind: GroupKind;
}

/** Single-line "new group" form (Kategoriler › Düzenle); confirms each create inline. */
function NewGroupForm({ kind }: NewGroupFormProps) {
  const { mutate: createGroup, isPending } = useCreateGroup();
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [created, setCreated] = useState('');

  const handleCreate = () => {
    if (!name.trim()) return;
    setError('');
    setCreated('');
    createGroup({ kind, name: name.trim() }, {
      onSuccess: (group) => {
        setName('');
        setCreated(group.name);
      },
      onError: (err) => setError(groupErrorText(err, 'Grup oluşturulurken hata oluştu.')),
    });
  };

  return (
    <div className="new-group-form">
      <div className="new-group-form-row">
        <input
          type="text"
          className="topic-input"
          placeholder="Yeni grup adı (ör. Avrupa)"
          aria-label="Yeni grup adı"
          maxLength={GROUP_NAME_MAX_LENGTH}
          value={name}
          onChange={(e) => { setName(e.target.value); setCreated(''); }}
          onKeyDown={(e) => { if (e.key === 'Enter') handleCreate(); }}
          disabled={isPending}
        />
        <button type="button" className="btn btn-primary btn-sm" onClick={handleCreate} disabled={isPending || !name.trim()}>
          {isPending ? 'Ekleniyor...' : 'Grup ekle'}
        </button>
      </div>
      {error && <p className="warning-text"><ExclamationTriangleIcon /> {error}</p>}
      {created && <p className="success-text"><CheckIcon /> "{created}" grubu eklendi.</p>}
    </div>
  );
}

export default NewGroupForm;
