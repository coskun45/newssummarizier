import { useState } from 'react';
import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  CheckIcon,
  XMarkIcon,
  ChevronUpIcon,
  ChevronDownIcon,
  DocumentArrowDownIcon,
  ArrowPathIcon,
} from '@heroicons/react/24/outline';
import { DateFilterSection } from '../DateFilter/DateFilter';
import {
  useBulletinCategories,
  useCreateBulletinCategory,
  useUpdateBulletinCategory,
  useDeleteBulletinCategory,
  useReorderBulletinCategories,
  useGenerateBulletin,
} from '../../hooks/useApi';
import { downloadBlob } from '../../utils/downloadFile';
import { PRIORITIES } from '../../constants/priorities';
import type { DateFilterState } from '../../types';
import './Bulletin.css';

const EMPTY_DATE_FILTER: DateFilterState = { preset: null, customFrom: '', customTo: '' };

function resolveDateRange(filter: DateFilterState): { from?: string; to?: string } {
  if (!filter.preset) return {};
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999).toISOString();
  if (filter.preset === 'today') return { from: todayStart, to: todayEnd };
  if (filter.preset === 'week') {
    const weekAgo = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 6).toISOString();
    return { from: weekAgo, to: todayEnd };
  }
  if (filter.preset === 'custom') {
    return {
      from: filter.customFrom ? new Date(filter.customFrom).toISOString() : undefined,
      to: filter.customTo ? new Date(filter.customTo + 'T23:59:59').toISOString() : undefined,
    };
  }
  return {};
}

/** The generate call uses responseType: 'blob', so an error response body
 * (e.g. a 400's {"detail": "..."}) also arrives as a Blob, not parsed JSON —
 * read it back out as text before parsing. */
async function extractErrorMessage(err: unknown): Promise<string> {
  const data = (err as { response?: { data?: unknown } })?.response?.data;
  if (data instanceof Blob) {
    try {
      const text = await data.text();
      const parsed = JSON.parse(text);
      if (parsed?.detail) return String(parsed.detail);
    } catch {
      // fall through to the generic message
    }
  }
  return 'Bülten oluşturulurken bir hata oluştu.';
}

function BulletinPanel() {
  const [dateFilter, setDateFilter] = useState<DateFilterState>(EMPTY_DATE_FILTER);
  const [selectedPriorities, setSelectedPriorities] = useState<string[]>([]);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editCategoryName, setEditCategoryName] = useState('');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const { data: categories, isLoading: categoriesLoading } = useBulletinCategories();
  const { mutate: createCategory, isPending: isCreatingCategory } = useCreateBulletinCategory();
  const { mutate: updateCategory, isPending: isUpdatingCategory } = useUpdateBulletinCategory();
  const { mutate: deleteCategory, isPending: isDeletingCategory } = useDeleteBulletinCategory();
  const { mutate: reorderCategories } = useReorderBulletinCategories();
  const generateMutation = useGenerateBulletin();

  const togglePriority = (value: string) => {
    setSelectedPriorities((prev) => (prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value]));
  };

  const handleAddCategory = () => {
    const name = newCategoryName.trim();
    if (!name) return;
    createCategory(name, { onSuccess: () => setNewCategoryName('') });
  };

  const handleStartEdit = (id: number, name: string) => {
    setEditingCategoryId(id);
    setEditCategoryName(name);
  };

  const handleSaveEdit = () => {
    if (editingCategoryId === null || !editCategoryName.trim()) return;
    updateCategory(
      { categoryId: editingCategoryId, name: editCategoryName.trim() },
      { onSuccess: () => setEditingCategoryId(null) }
    );
  };

  const handleDeleteCategory = (id: number, name: string) => {
    if (confirm(`"${name}" kategorisini silmek istediğinizden emin misiniz?`)) {
      deleteCategory(id);
    }
  };

  const moveCategory = (index: number, direction: -1 | 1) => {
    if (!categories) return;
    const target = index + direction;
    if (target < 0 || target >= categories.length) return;
    const next = [...categories];
    [next[index], next[target]] = [next[target], next[index]];
    reorderCategories(next.map((c) => c.id));
  };

  const handleGenerate = async () => {
    setErrorMessage(null);
    setStatusMessage(null);
    const range = resolveDateRange(dateFilter);
    try {
      const blob = await generateMutation.mutateAsync({
        published_from: range.from,
        published_to: range.to,
        priorities: selectedPriorities.length > 0 ? selectedPriorities : undefined,
      });
      const stamp = format(new Date(), 'yyyy-MM-dd', { locale: tr });
      downloadBlob(blob, `bulten-${stamp}.docx`);
      setStatusMessage('Bülten oluşturuldu ve indirildi.');
    } catch (err) {
      setErrorMessage(await extractErrorMessage(err));
    }
  };

  const hasCategories = !!categories && categories.length > 0;

  return (
    <div className="bulletin-panel">
      <div className="bulletin-panel-grid">
        <section className="bulletin-section">
          <h3 className="bulletin-section-title">Zaman Aralığı</h3>
          <p className="bulletin-section-description">
            Seçim yapılmazsa son 24 saat içindeki haberler kullanılır.
          </p>
          <DateFilterSection title="Yayın Tarihi" value={dateFilter} onChange={setDateFilter} />
        </section>

        <section className="bulletin-section">
          <h3 className="bulletin-section-title">Önem Seviyesi</h3>
          <p className="bulletin-section-description">
            Seçim yapılmazsa tüm önem seviyelerindeki haberler dahil edilir.
          </p>
          <div className="checkbox-group">
            {PRIORITIES.map((p) => (
              <label key={p.value} className="bulletin-checkbox-label">
                <input
                  type="checkbox"
                  checked={selectedPriorities.includes(p.value)}
                  onChange={() => togglePriority(p.value)}
                />
                <span>{p.label}</span>
              </label>
            ))}
          </div>
        </section>

        <section className="bulletin-section bulletin-section--wide">
          <h3 className="bulletin-section-title">Üst Düzey Kategoriler</h3>
          <p className="bulletin-section-description">
            Bültendeki ana başlıklar (ör. Avrupa, Amerika). Alt başlıklar her üretimde haberlere göre
            otomatik oluşturulur.
          </p>

          {categoriesLoading ? (
            <p className="text-small text-muted">Yükleniyor...</p>
          ) : !hasCategories ? (
            <p className="text-small text-muted">Henüz kategori tanımlanmadı.</p>
          ) : (
            <ul className="bulletin-category-list">
              {categories!.map((category, index) => (
                <li key={category.id} className="bulletin-category-item">
                  {editingCategoryId === category.id ? (
                    <div className="bulletin-category-edit-form">
                      <input
                        type="text"
                        className="input"
                        value={editCategoryName}
                        onChange={(e) => setEditCategoryName(e.target.value)}
                        disabled={isUpdatingCategory}
                      />
                      <button
                        className="btn btn-icon btn-outline"
                        onClick={() => setEditingCategoryId(null)}
                        disabled={isUpdatingCategory}
                        aria-label="İptal"
                      >
                        <XMarkIcon />
                      </button>
                      <button
                        className="btn btn-icon btn-primary"
                        onClick={handleSaveEdit}
                        disabled={isUpdatingCategory || !editCategoryName.trim()}
                        aria-label="Kaydet"
                      >
                        <CheckIcon />
                      </button>
                    </div>
                  ) : (
                    <>
                      <span className="bulletin-category-name">{category.name}</span>
                      <div className="bulletin-category-actions">
                        <button
                          className="btn btn-icon btn-secondary"
                          onClick={() => moveCategory(index, -1)}
                          disabled={index === 0}
                          aria-label="Yukarı taşı"
                        >
                          <ChevronUpIcon />
                        </button>
                        <button
                          className="btn btn-icon btn-secondary"
                          onClick={() => moveCategory(index, 1)}
                          disabled={index === categories!.length - 1}
                          aria-label="Aşağı taşı"
                        >
                          <ChevronDownIcon />
                        </button>
                        <button
                          className="btn btn-icon btn-secondary"
                          onClick={() => handleStartEdit(category.id, category.name)}
                          aria-label="Düzenle"
                        >
                          <PencilIcon />
                        </button>
                        <button
                          className="btn btn-icon btn-secondary"
                          onClick={() => handleDeleteCategory(category.id, category.name)}
                          disabled={isDeletingCategory}
                          aria-label="Sil"
                        >
                          <TrashIcon />
                        </button>
                      </div>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}

          <div className="bulletin-category-add-form">
            <input
              type="text"
              className="input"
              placeholder="Yeni kategori (ör. Avrupa)"
              value={newCategoryName}
              onChange={(e) => setNewCategoryName(e.target.value)}
              disabled={isCreatingCategory}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleAddCategory();
              }}
            />
            <button
              className="btn btn-primary btn-sm"
              onClick={handleAddCategory}
              disabled={isCreatingCategory || !newCategoryName.trim()}
            >
              <PlusIcon /> Ekle
            </button>
          </div>
        </section>
      </div>

      <div className="bulletin-generate-bar">
        <button
          className="btn btn-primary btn-lg"
          onClick={handleGenerate}
          disabled={generateMutation.isPending || !hasCategories}
          title={!hasCategories ? 'Önce en az bir kategori ekleyin' : undefined}
        >
          {generateMutation.isPending ? (
            <>
              <ArrowPathIcon className="spin-icon" /> Oluşturuluyor...
            </>
          ) : (
            <>
              <DocumentArrowDownIcon /> Oluştur ve İndir
            </>
          )}
        </button>
        {statusMessage && <span className="bulletin-status-message">{statusMessage}</span>}
        {errorMessage && (
          <span className="bulletin-status-message bulletin-status-message--error">{errorMessage}</span>
        )}
      </div>
    </div>
  );
}

export default BulletinPanel;
