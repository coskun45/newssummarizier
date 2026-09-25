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
  useBulletinPreviewCount,
  useGeneratedBulletins,
  useDownloadGeneratedBulletin,
  useDeleteGeneratedBulletin,
} from '../../hooks/useApi';
import { downloadBlob } from '../../utils/downloadFile';
import { showToast } from '../../lib/toast';
import { PRIORITIES } from '../../constants/priorities';
import type { BulletinGenerateRequest, DateFilterState, GeneratedBulletin } from '../../types';
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

function formatGeneratedBulletinMeta(bulletin: GeneratedBulletin): string {
  const range = bulletin.published_from && bulletin.published_to
    ? `${format(new Date(bulletin.published_from), 'd MMM HH:mm', { locale: tr })} – ${format(new Date(bulletin.published_to), 'd MMM HH:mm', { locale: tr })}`
    : 'Son 24 saat';

  const selectionLabels = (bulletin.priorities ?? []).map(
    (value) => PRIORITIES.find((p) => p.value === value)?.label ?? value
  );
  if (bulletin.include_favorites) selectionLabels.push('Favoriler');
  const selection = selectionLabels.length > 0 ? selectionLabels.join(', ') : 'Tüm önem seviyeleri';

  return `${range} · ${selection} · ${bulletin.article_count} haber özeti`;
}

/** The generate call uses responseType: 'blob', so an error response body
 * (e.g. a 400's {"detail": "..."}) also arrives as a Blob, not parsed JSON —
 * read it back out as text before parsing. */
async function extractErrorMessage(
  err: unknown,
  fallback = 'Bülten oluşturulurken bir hata oluştu.'
): Promise<string> {
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
  return fallback;
}

interface BulletinPanelProps {
  /** Generated reports are shared by all users, so only admins may delete them. */
  isAdmin?: boolean;
}

function BulletinPanel({ isAdmin = false }: BulletinPanelProps) {
  const [dateFilter, setDateFilter] = useState<DateFilterState>(EMPTY_DATE_FILTER);
  const [selectedPriorities, setSelectedPriorities] = useState<string[]>([]);
  const [includeFavorites, setIncludeFavorites] = useState(false);
  const [newCategoryName, setNewCategoryName] = useState('');
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editCategoryName, setEditCategoryName] = useState('');

  const { data: categories, isLoading: categoriesLoading } = useBulletinCategories();
  const { mutate: createCategory, isPending: isCreatingCategory } = useCreateBulletinCategory();
  const { mutate: updateCategory, isPending: isUpdatingCategory } = useUpdateBulletinCategory();
  const { mutate: deleteCategory, isPending: isDeletingCategory } = useDeleteBulletinCategory();
  const { mutate: reorderCategories } = useReorderBulletinCategories();
  const generateMutation = useGenerateBulletin();
  const { data: generatedBulletins, isLoading: generatedLoading } = useGeneratedBulletins();
  const downloadGeneratedMutation = useDownloadGeneratedBulletin();
  const { mutate: deleteGenerated } = useDeleteGeneratedBulletin();

  const togglePriority = (value: string) => {
    setSelectedPriorities((prev) => (prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value]));
  };

  const resolvedRange = resolveDateRange(dateFilter);
  const bulletinParams: BulletinGenerateRequest = {
    published_from: resolvedRange.from,
    published_to: resolvedRange.to,
    priorities: selectedPriorities.length > 0 ? selectedPriorities : undefined,
    include_favorites: includeFavorites || undefined,
  };
  const { data: previewCountData, isFetching: previewCountLoading, isError: previewCountError } =
    useBulletinPreviewCount(bulletinParams);
  // The backend rejects /generate when nothing matches, so don't offer it. Only a known 0
  // disables — while the count loads or if the preview fails, generation stays possible.
  const hasNoMatchingArticles = !previewCountLoading && !previewCountError && previewCountData?.count === 0;

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
    try {
      const { blob, filename } = await generateMutation.mutateAsync(bulletinParams);
      downloadBlob(blob, filename);
      showToast('Bülten oluşturuldu ve indirildi.', 'success');
    } catch (err) {
      showToast(await extractErrorMessage(err), 'error');
    }
  };

  const handleDownloadGenerated = async (bulletin: GeneratedBulletin) => {
    try {
      const blob = await downloadGeneratedMutation.mutateAsync(bulletin.id);
      downloadBlob(blob, bulletin.filename);
      showToast('Bülten indirildi.', 'success');
    } catch (err) {
      showToast(await extractErrorMessage(err, 'Bülten indirilemedi.'), 'error');
    }
  };

  const handleDeleteGenerated = (bulletin: GeneratedBulletin) => {
    if (confirm(`"${bulletin.filename}" bültenini silmek istediğinizden emin misiniz?`)) {
      deleteGenerated(bulletin.id, { onSuccess: () => showToast('Bülten silindi.', 'success') });
    }
  };

  const hasCategories = !!categories && categories.length > 0;
  const hasGeneratedBulletins = !!generatedBulletins && generatedBulletins.length > 0;

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
            Seçim yapılmazsa tüm önem seviyelerindeki haberler dahil edilir. Favoriler işaretlenirse,
            önem seviyesinden bağımsız olarak favori haberler de bültene eklenir.
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
            <label className="bulletin-checkbox-label">
              <input
                type="checkbox"
                checked={includeFavorites}
                onChange={() => setIncludeFavorites((prev) => !prev)}
              />
              <span>Favoriler</span>
            </label>
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
        {!previewCountError && (
          <span className="bulletin-preview-count">
            {previewCountLoading
              ? 'Haber sayısı hesaplanıyor…'
              : `Bu seçimlerle ${previewCountData?.count ?? 0} haber özeti bültende yer alacak.`}
          </span>
        )}
        <button
          className="btn btn-primary btn-lg bulletin-generate-btn"
          onClick={handleGenerate}
          disabled={generateMutation.isPending || !hasCategories || hasNoMatchingArticles}
          title={
            !hasCategories
              ? 'Önce en az bir kategori ekleyin'
              : hasNoMatchingArticles
                ? 'Bu seçimlerle bültene girecek haber yok'
                : undefined
          }
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
      </div>

      <section className="bulletin-section bulletin-section--wide">
        <h3 className="bulletin-section-title">Daha Önce Oluşturulan Bültenler</h3>

        {generatedLoading ? (
          <p className="text-small text-muted">Yükleniyor...</p>
        ) : !hasGeneratedBulletins ? (
          <p className="text-small text-muted">Henüz oluşturulmuş bülten yok.</p>
        ) : (
          <ul className="generated-bulletins-list">
            {generatedBulletins!.map((bulletin) => (
              <li key={bulletin.id} className="generated-bulletin-item">
                <div className="generated-bulletin-info">
                  <span className="generated-bulletin-date">
                    {format(new Date(bulletin.generated_at), 'd MMM yyyy HH:mm', { locale: tr })}
                  </span>
                  <span className="generated-bulletin-meta">{formatGeneratedBulletinMeta(bulletin)}</span>
                </div>
                <div className="generated-bulletin-actions">
                  <button
                    className="btn btn-icon btn-secondary"
                    onClick={() => handleDownloadGenerated(bulletin)}
                    disabled={downloadGeneratedMutation.isPending}
                    aria-label="İndir"
                  >
                    <DocumentArrowDownIcon />
                  </button>
                  {isAdmin && (
                    <button
                      className="btn btn-icon btn-secondary"
                      onClick={() => handleDeleteGenerated(bulletin)}
                      aria-label="Sil"
                    >
                      <TrashIcon />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export default BulletinPanel;
