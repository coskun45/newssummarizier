import { useState } from 'react';
import type { FormEvent } from 'react';
import { format } from 'date-fns';
import { tr } from 'date-fns/locale';
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  PauseIcon,
  PlayIcon,
  PaperAirplaneIcon,
  ClockIcon,
  EnvelopeIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
} from '@heroicons/react/24/outline';
import {
  useNewsletterStatus,
  useNewsletterSubscriptions,
  useAllNewsletterSubscriptions,
  useNewsletterDeliveries,
  useCreateNewsletterSubscription,
  useUpdateNewsletterSubscription,
  useDeleteNewsletterSubscription,
  usePauseNewsletterSubscription,
  useResumeNewsletterSubscription,
  useResendNewsletterConfirmation,
  useSendNewsletterNow,
} from '../../hooks/useApi';
import { showToast } from '../../lib/toast';
import { PRIORITIES } from '../../constants/priorities';
import type {
  BulletinCategory,
  BulletinPriority,
  NewsletterDelivery,
  NewsletterDeliveryStatus,
  NewsletterFormat,
  NewsletterStatus,
  NewsletterSubscription,
  NewsletterSubscriptionInput,
} from '../../types';
import './NewsletterSubscriptions.css';

const WEEKDAYS = ['Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi', 'Pazar'];
const HOURS = Array.from({ length: 24 }, (_, h) => h);

const FORMAT_OPTIONS: { value: NewsletterFormat; label: string; hint: string }[] = [
  { value: 'docx', label: 'Sadece Word dosyası', hint: 'Bülten mailin ekinde .docx olarak gelir' },
  { value: 'email', label: 'Sadece mail', hint: 'Bülten doğrudan mailin içinde yer alır' },
  { value: 'both', label: 'İkisi de', hint: 'Bülten mailin içinde, Word dosyası da ekte' },
];

const STATUS_LABELS: Record<NewsletterStatus, string> = {
  pending: 'Onay bekliyor',
  active: 'Aktif',
  paused: 'Durduruldu',
  unsubscribed: 'Abonelikten çıkıldı',
  disabled: 'Devre dışı',
};

const DELIVERY_LABELS: Record<NewsletterDeliveryStatus, string> = {
  sent: 'Gönderildi',
  failed: 'Başarısız',
  skipped_no_articles: 'Haber yok (bilgi maili)',
  skipped_cost_limit: 'Maliyet limiti (bilgi maili)',
  skipped_no_categories: 'Atlandı: kategori tanımlı değil',
  skipped_build_error: 'Bülten hazırlanamadı',
};

function apiErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === 'string' ? detail : fallback;
}

function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, '0')}:00`;
}

function scheduleLabel(sub: NewsletterSubscriptionInput): string {
  if (sub.frequency === 'weekly') {
    return `Haftalık · her ${WEEKDAYS[sub.send_weekday ?? 0]} ${hourLabel(sub.send_hour)}`;
  }
  return `Günlük · her gün ${hourLabel(sub.send_hour)}`;
}

function filterLabel(sub: NewsletterSubscriptionInput, categories: BulletinCategory[]): string {
  const priorities = sub.priorities.map((p) => PRIORITIES.find((o) => o.value === p)?.label ?? p);
  if (sub.include_favorites) priorities.push('Favoriler');
  const categoryNames = categories.filter((c) => sub.category_ids.includes(c.id)).map((c) => c.name);
  return [
    `en fazla ${sub.max_articles} haber`,
    priorities.length > 0 ? priorities.join(', ') : 'tüm önem seviyeleri',
    categoryNames.length > 0 ? categoryNames.join(', ') : 'tüm kategoriler',
    FORMAT_OPTIONS.find((f) => f.value === sub.delivery_format)?.label ?? sub.delivery_format,
  ].join(' · ');
}

function formatDate(value: string): string {
  return format(new Date(value), 'd MMM yyyy HH:mm', { locale: tr });
}

function emptyInput(email: string): NewsletterSubscriptionInput {
  return {
    email,
    frequency: 'daily',
    send_hour: 8,
    send_weekday: null,
    max_articles: 10,
    priorities: [],
    include_favorites: false,
    category_ids: [],
    delivery_format: 'both',
  };
}

function toInput(sub: NewsletterSubscription): NewsletterSubscriptionInput {
  return {
    email: sub.email,
    frequency: sub.frequency,
    send_hour: sub.send_hour,
    send_weekday: sub.send_weekday,
    max_articles: sub.max_articles,
    priorities: sub.priorities,
    include_favorites: sub.include_favorites,
    category_ids: sub.category_ids,
    delivery_format: sub.delivery_format,
  };
}

// ==================== Form ====================

interface SubscriptionFormProps {
  initial: NewsletterSubscriptionInput;
  categories: BulletinCategory[];
  maxArticlesLimit: number;
  ownEmail: string;
  isEditing: boolean;
  isSaving: boolean;
  onCancel: () => void;
  onSubmit: (input: NewsletterSubscriptionInput) => void;
}

function SubscriptionForm({
  initial,
  categories,
  maxArticlesLimit,
  ownEmail,
  isEditing,
  isSaving,
  onCancel,
  onSubmit,
}: SubscriptionFormProps) {
  const [form, setForm] = useState<NewsletterSubscriptionInput>(initial);
  const update = (patch: Partial<NewsletterSubscriptionInput>) => setForm((prev) => ({ ...prev, ...patch }));

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value];

  const isForeignEmail = form.email.trim().toLowerCase() !== ownEmail.trim().toLowerCase();
  const maxArticlesValid = form.max_articles >= 1 && form.max_articles <= maxArticlesLimit;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit({
      ...form,
      email: form.email.trim(),
      send_weekday: form.frequency === 'weekly' ? (form.send_weekday ?? 0) : null,
    });
  };

  return (
    <form className="newsletter-form" onSubmit={handleSubmit} aria-label="Abonelik formu">
      <div className="newsletter-form-grid">
        <div className="newsletter-field newsletter-field--wide">
          <label htmlFor="newsletter-email">E-posta adresi</label>
          <input
            id="newsletter-email"
            type="email"
            className="input"
            required
            value={form.email}
            onChange={(e) => update({ email: e.target.value })}
          />
          {isForeignEmail && form.email.includes('@') && (
            <span className="newsletter-hint">
              Bu adrese önce bir onay maili gider; bağlantıya tıklanana kadar bülten gönderilmez.
            </span>
          )}
        </div>

        <fieldset className="newsletter-field">
          <legend>Sıklık</legend>
          <div className="newsletter-radio-row">
            <label className="newsletter-choice">
              <input
                type="radio"
                name="frequency"
                checked={form.frequency === 'daily'}
                onChange={() => update({ frequency: 'daily' })}
              />
              Günlük
            </label>
            <label className="newsletter-choice">
              <input
                type="radio"
                name="frequency"
                checked={form.frequency === 'weekly'}
                onChange={() => update({ frequency: 'weekly', send_weekday: form.send_weekday ?? 0 })}
              />
              Haftalık
            </label>
          </div>
          <span className="newsletter-hint">
            {form.frequency === 'weekly'
              ? 'Gönderim anından geriye son 7 günün haberleri.'
              : 'Gönderim anından geriye son 24 saatin haberleri.'}
          </span>
        </fieldset>

        <div className="newsletter-field newsletter-field--inline">
          {form.frequency === 'weekly' && (
            <div>
              <label htmlFor="newsletter-weekday">Gün</label>
              <select
                id="newsletter-weekday"
                className="select"
                value={form.send_weekday ?? 0}
                onChange={(e) => update({ send_weekday: Number(e.target.value) })}
              >
                {WEEKDAYS.map((day, index) => (
                  <option key={day} value={index}>{day}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label htmlFor="newsletter-hour">Saat</label>
            <select
              id="newsletter-hour"
              className="select"
              value={form.send_hour}
              onChange={(e) => update({ send_hour: Number(e.target.value) })}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>{hourLabel(h)}</option>
              ))}
            </select>
          </div>
          <div>
            <label htmlFor="newsletter-max">En fazla haber</label>
            <input
              id="newsletter-max"
              type="number"
              className="input"
              min={1}
              max={maxArticlesLimit}
              value={Number.isNaN(form.max_articles) ? '' : form.max_articles}
              onChange={(e) => update({ max_articles: e.target.valueAsNumber })}
            />
          </div>
        </div>

        <fieldset className="newsletter-field">
          <legend>Önem seviyesi</legend>
          <div className="newsletter-check-grid">
            {PRIORITIES.map((p) => (
              <label key={p.value} className="newsletter-choice">
                <input
                  type="checkbox"
                  checked={form.priorities.includes(p.value as BulletinPriority)}
                  onChange={() => update({ priorities: toggle(form.priorities, p.value as BulletinPriority) })}
                />
                {p.label}
              </label>
            ))}
            <label className="newsletter-choice">
              <input
                type="checkbox"
                checked={form.include_favorites}
                onChange={() => update({ include_favorites: !form.include_favorites })}
              />
              Favoriler
            </label>
          </div>
          <span className="newsletter-hint">
            {form.priorities.length === 0 && form.include_favorites
              ? 'Yalnızca Favoriler işaretliyse sadece favori haberler gelir.'
              : 'Seçim yapılmazsa tüm önem seviyeleri; Favoriler seçilenlere ek olarak favori haberleri de katar.'}{' '}
            Haber fazlaysa önce önemli, sonra en yeni haberler alınır.
          </span>
        </fieldset>

        <fieldset className="newsletter-field">
          <legend>Üst düzey kategoriler</legend>
          {categories.length === 0 ? (
            <span className="newsletter-hint">Henüz kategori tanımlanmadı.</span>
          ) : (
            <div className="newsletter-check-grid">
              {categories.map((c) => (
                <label key={c.id} className="newsletter-choice">
                  <input
                    type="checkbox"
                    checked={form.category_ids.includes(c.id)}
                    onChange={() => update({ category_ids: toggle(form.category_ids, c.id) })}
                  />
                  {c.name}
                </label>
              ))}
            </div>
          )}
          <span className="newsletter-hint">Seçim yapılmazsa tüm kategoriler.</span>
        </fieldset>

        <fieldset className="newsletter-field newsletter-field--wide">
          <legend>Format</legend>
          <div className="newsletter-format-row">
            {FORMAT_OPTIONS.map((option) => (
              <label
                key={option.value}
                className={`newsletter-format-option${form.delivery_format === option.value ? ' newsletter-format-option--active' : ''}`}
              >
                <input
                  type="radio"
                  name="delivery_format"
                  checked={form.delivery_format === option.value}
                  onChange={() => update({ delivery_format: option.value })}
                />
                <span className="newsletter-format-label">{option.label}</span>
                <span className="newsletter-hint">{option.hint}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div className="newsletter-form-actions">
        <button type="button" className="btn btn-outline" onClick={onCancel} disabled={isSaving}>
          İptal
        </button>
        <button type="submit" className="btn btn-primary" disabled={isSaving || !maxArticlesValid}>
          {isSaving ? 'Kaydediliyor…' : isEditing ? 'Kaydet' : 'Abone Ol'}
        </button>
      </div>
    </form>
  );
}

// ==================== Delivery history ====================

function DeliveryHistory({ subscriptionId }: { subscriptionId: number }) {
  const { data: deliveries, isLoading } = useNewsletterDeliveries(subscriptionId);

  if (isLoading) return <p className="text-small text-muted">Yükleniyor...</p>;
  if (!deliveries || deliveries.length === 0) {
    return <p className="text-small text-muted">Henüz gönderim yapılmadı.</p>;
  }
  return (
    <ul className="newsletter-history" aria-label="Gönderim geçmişi">
      {deliveries.map((d: NewsletterDelivery) => (
        <li key={d.id} className={`newsletter-history-item newsletter-history-item--${d.status}`}>
          <span className="newsletter-history-date">{formatDate(d.sent_at)}</span>
          <span className="newsletter-history-status">{DELIVERY_LABELS[d.status] ?? d.status}</span>
          <span className="newsletter-history-meta">
            {d.article_count > 0 && `${d.article_count} haber`}
            {d.manual && ' · Şimdi gönder'}
            {d.attempts > 1 && ` · ${d.attempts} deneme`}
          </span>
          {d.error && <span className="newsletter-history-error">{d.error}</span>}
        </li>
      ))}
    </ul>
  );
}

// ==================== Subscription card ====================

interface SubscriptionCardProps {
  subscription: NewsletterSubscription;
  categories: BulletinCategory[];
  onEdit: (sub: NewsletterSubscription) => void;
}

function SubscriptionCard({ subscription: sub, categories, onEdit }: SubscriptionCardProps) {
  const [showHistory, setShowHistory] = useState(false);
  const pause = usePauseNewsletterSubscription();
  const resume = useResumeNewsletterSubscription();
  const remove = useDeleteNewsletterSubscription();
  const resend = useResendNewsletterConfirmation();
  const sendNow = useSendNewsletterNow();

  const run = <T,>(promise: Promise<T>, success: string, failure: string) =>
    promise.then(
      () => showToast(success, 'success'),
      (err) => showToast(apiErrorMessage(err, failure), 'error'),
    );

  const handleDelete = () => {
    if (confirm(`${sub.email} aboneliğini silmek istediğinizden emin misiniz?`)) {
      run(remove.mutateAsync(sub.id), 'Abonelik silindi.', 'Abonelik silinemedi.');
    }
  };

  const handleSendNow = () => {
    sendNow.mutateAsync(sub.id).then(
      () => {
        setShowHistory(true);
        showToast('Bülten hazırlanıyor; birkaç dakika içinde gönderilir. Sonuç Geçmiş\'te görünür.', 'success');
      },
      (err) => showToast(apiErrorMessage(err, 'Bülten gönderilemedi.'), 'error'),
    );
  };

  const canResume = sub.status === 'paused' || sub.status === 'disabled' || sub.status === 'unsubscribed';

  return (
    <li className="newsletter-card" aria-label={`Abonelik ${sub.email}`}>
      <div className="newsletter-card-main">
        <div className="newsletter-card-title">
          <EnvelopeIcon />
          <span className="newsletter-card-email">{sub.email}</span>
          <span className={`badge newsletter-status newsletter-status--${sub.status}`}>{STATUS_LABELS[sub.status]}</span>
        </div>
        <div className="newsletter-card-meta">{scheduleLabel(sub)}</div>
        <div className="newsletter-card-meta">{filterLabel(sub, categories)}</div>
        {sub.last_sent_at && (
          <div className="newsletter-card-meta newsletter-card-meta--muted">
            Son planlı gönderim: {formatDate(sub.last_sent_at)}
          </div>
        )}
        {sub.status === 'pending' && (
          <div className="newsletter-card-note">
            {sub.confirm_sent_at
              ? `Onay maili ${formatDate(sub.confirm_sent_at)} tarihinde gönderildi; onaylanınca bülten gitmeye başlar.`
              : 'Onay maili gönderilemedi. "Onay mailini tekrar gönder" ile yeniden deneyin.'}
          </div>
        )}
        {sub.status === 'disabled' && (
          <div className="newsletter-card-note newsletter-card-note--danger">
            Üst üste {sub.consecutive_failures} gönderim başarısız olduğu için durduruldu. Adresi kontrol edip
            sürdürebilirsiniz.
          </div>
        )}
        {sub.status === 'unsubscribed' && (
          <div className="newsletter-card-note">Alıcı maildeki bağlantıyla abonelikten çıktı.</div>
        )}
      </div>

      <div className="newsletter-card-actions">
        <button className="btn btn-sm btn-outline" onClick={() => onEdit(sub)}>
          <PencilIcon /> Düzenle
        </button>
        {sub.status === 'active' && (
          <button
            className="btn btn-sm btn-outline"
            onClick={() => run(pause.mutateAsync(sub.id), 'Abonelik durduruldu.', 'Abonelik durdurulamadı.')}
            disabled={pause.isPending}
          >
            <PauseIcon /> Durdur
          </button>
        )}
        {canResume && (
          <button
            className="btn btn-sm btn-outline"
            onClick={() => run(resume.mutateAsync(sub.id), 'Abonelik sürdürüldü.', 'Abonelik sürdürülemedi.')}
            disabled={resume.isPending}
          >
            <PlayIcon /> Sürdür
          </button>
        )}
        {sub.status === 'pending' && (
          <button
            className="btn btn-sm btn-outline"
            onClick={() => run(resend.mutateAsync(sub.id), 'Onay maili gönderildi.', 'Onay maili gönderilemedi.')}
            disabled={resend.isPending}
          >
            <ArrowPathIcon /> Onay mailini tekrar gönder
          </button>
        )}
        {sub.status !== 'pending' && sub.status !== 'unsubscribed' && (
          <button
            className="btn btn-sm btn-outline"
            onClick={handleSendNow}
            disabled={sendNow.isPending}
            title="Bülteni şimdi oluşturup gönderir (saatte en fazla bir kez)"
          >
            {sendNow.isPending ? <ArrowPathIcon className="spin-icon" /> : <PaperAirplaneIcon />}
            Şimdi gönder
          </button>
        )}
        <button
          className="btn btn-sm btn-outline"
          onClick={() => setShowHistory((v) => !v)}
          aria-expanded={showHistory}
        >
          <ClockIcon /> Geçmiş
        </button>
        <button className="btn btn-sm btn-outline" onClick={handleDelete} disabled={remove.isPending}>
          <TrashIcon /> Sil
        </button>
      </div>

      {showHistory && (
        <div className="newsletter-card-history">
          <DeliveryHistory subscriptionId={sub.id} />
        </div>
      )}
    </li>
  );
}

// ==================== Admin table ====================

function AdminSubscriptionsTable({ categories }: { categories: BulletinCategory[] }) {
  const { data, isLoading } = useAllNewsletterSubscriptions(true);
  const pause = usePauseNewsletterSubscription();
  const resume = useResumeNewsletterSubscription();
  const remove = useDeleteNewsletterSubscription();

  const onError = (err: unknown) => showToast(apiErrorMessage(err, 'İşlem başarısız.'), 'error');

  return (
    <section className="bulletin-section bulletin-section--wide" aria-label="Tüm Aboneler">
      <h3 className="bulletin-section-title">Tüm Aboneler</h3>
      {data && (
        <p className="bulletin-section-description">
          Son 30 günde abonelik bültenlerinin yapay zekâ maliyeti: ${data.cost_last_30_days.toFixed(2)}
        </p>
      )}
      {data?.categories_missing && (
        <div className="newsletter-warning">
          <ExclamationTriangleIcon /> Hiç üst düzey kategori tanımlı değil — abonelik bültenleri gönderilmiyor.
        </div>
      )}
      {isLoading ? (
        <p className="text-small text-muted">Yükleniyor...</p>
      ) : !data || data.subscriptions.length === 0 ? (
        <p className="text-small text-muted">Henüz abone yok.</p>
      ) : (
        <div className="newsletter-table-wrap">
          <table className="newsletter-table">
            <thead>
              <tr>
                <th>Sahibi</th>
                <th>Alıcı</th>
                <th>Plan</th>
                <th>Filtre</th>
                <th>Durum</th>
                <th aria-label="İşlemler" />
              </tr>
            </thead>
            <tbody>
              {data.subscriptions.map((sub) => (
                <tr key={sub.id}>
                  <td>{sub.owner_email}</td>
                  <td>{sub.email}</td>
                  <td>{scheduleLabel(sub)}</td>
                  <td className="newsletter-table-filter">{filterLabel(sub, categories)}</td>
                  <td>
                    <span className={`badge newsletter-status newsletter-status--${sub.status}`}>
                      {STATUS_LABELS[sub.status]}
                    </span>
                  </td>
                  <td className="newsletter-table-actions">
                    {sub.status === 'active' && (
                      <button
                        className="btn btn-icon btn-secondary"
                        aria-label={`${sub.email} aboneliğini durdur`}
                        onClick={() => pause.mutate(sub.id, { onError })}
                      >
                        <PauseIcon />
                      </button>
                    )}
                    {(sub.status === 'paused' || sub.status === 'disabled') && (
                      <button
                        className="btn btn-icon btn-secondary"
                        aria-label={`${sub.email} aboneliğini sürdür`}
                        onClick={() => resume.mutate(sub.id, { onError })}
                      >
                        <PlayIcon />
                      </button>
                    )}
                    <button
                      className="btn btn-icon btn-secondary"
                      aria-label={`${sub.email} aboneliğini sil`}
                      onClick={() => {
                        if (confirm(`${sub.email} aboneliğini silmek istediğinizden emin misiniz?`)) {
                          remove.mutate(sub.id, { onError });
                        }
                      }}
                    >
                      <TrashIcon />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ==================== Panel ====================

interface NewsletterSubscriptionsProps {
  isAdmin?: boolean;
  currentUserEmail?: string;
  categories?: BulletinCategory[];
}

type FormState = { mode: 'closed' } | { mode: 'create' } | { mode: 'edit'; subscription: NewsletterSubscription };

function NewsletterSubscriptions({ isAdmin = false, currentUserEmail = '', categories = [] }: NewsletterSubscriptionsProps) {
  const [formState, setFormState] = useState<FormState>({ mode: 'closed' });
  const { data: status } = useNewsletterStatus();
  const { data: subscriptions, isLoading } = useNewsletterSubscriptions();
  const createMutation = useCreateNewsletterSubscription();
  const updateMutation = useUpdateNewsletterSubscription();

  const handleSubmit = (input: NewsletterSubscriptionInput) => {
    const editing = formState.mode === 'edit' ? formState.subscription : null;
    const request = editing
      ? updateMutation.mutateAsync({ id: editing.id, payload: input })
      : createMutation.mutateAsync(input);
    request.then(
      (saved) => {
        setFormState({ mode: 'closed' });
        // A confirmation mail only goes out when the subscription newly became pending
        // (new foreign address), not when a pending one's schedule/filters are edited.
        const newlyPending = saved.status === 'pending' && (!editing || editing.status !== 'pending' ||
          editing.email !== saved.email);
        if (newlyPending) {
          showToast(
            saved.confirm_sent_at
              ? `${saved.email} adresine onay maili gönderildi.`
              : 'Abonelik kaydedildi ancak onay maili gönderilemedi.',
            saved.confirm_sent_at ? 'success' : 'error',
          );
        } else {
          showToast(editing ? 'Abonelik güncellendi.' : 'Abonelik oluşturuldu.', 'success');
        }
      },
      (err) => showToast(apiErrorMessage(err, 'Abonelik kaydedilemedi.'), 'error'),
    );
  };

  const limitReached = !!status && !!subscriptions &&
    subscriptions.filter((s) => s.status !== 'unsubscribed').length >= status.max_subscriptions;

  return (
    <div className="newsletter-panel">
      <section className="bulletin-section bulletin-section--wide">
        <div className="newsletter-header">
          <div>
            <h3 className="bulletin-section-title">Bülten Aboneliği</h3>
            <p className="bulletin-section-description">
              Bülten seçtiğiniz sıklıkta e-posta ile gelsin. Her mailin altındaki bağlantıyla abonelikten
              çıkılabilir. Saatler {status?.timezone ?? 'Europe/Berlin'} saat dilimindedir.
            </p>
          </div>
          {formState.mode === 'closed' && (
            <button
              className="btn btn-primary"
              onClick={() => setFormState({ mode: 'create' })}
              disabled={limitReached}
              title={limitReached ? `En fazla ${status?.max_subscriptions} abonelik oluşturabilirsiniz` : undefined}
            >
              <PlusIcon /> Yeni Abonelik
            </button>
          )}
        </div>

        {status && !status.email_configured && (
          <div className="newsletter-warning" role="alert">
            <ExclamationTriangleIcon /> E-posta gönderimi yapılandırılmamış. Abonelikler kaydedilir ancak mail
            gönderilmez — yöneticinizin SMTP ayarlarını yapması gerekiyor.
          </div>
        )}

        {formState.mode !== 'closed' && (
          <SubscriptionForm
            key={formState.mode === 'edit' ? formState.subscription.id : 'new'}
            initial={formState.mode === 'edit' ? toInput(formState.subscription) : emptyInput(currentUserEmail)}
            categories={categories}
            maxArticlesLimit={status?.max_articles_limit ?? 50}
            ownEmail={formState.mode === 'edit' ? formState.subscription.owner_email : currentUserEmail}
            isEditing={formState.mode === 'edit'}
            isSaving={createMutation.isPending || updateMutation.isPending}
            onCancel={() => setFormState({ mode: 'closed' })}
            onSubmit={handleSubmit}
          />
        )}
      </section>

      <section className="bulletin-section bulletin-section--wide" aria-label="Aboneliklerim">
        <h3 className="bulletin-section-title">Aboneliklerim</h3>
        {isLoading ? (
          <p className="text-small text-muted">Yükleniyor...</p>
        ) : !subscriptions || subscriptions.length === 0 ? (
          <p className="text-small text-muted">Henüz aboneliğiniz yok.</p>
        ) : (
          <ul className="newsletter-list">
            {subscriptions.map((sub) => (
              <SubscriptionCard
                key={sub.id}
                subscription={sub}
                categories={categories}
                onEdit={(s) => setFormState({ mode: 'edit', subscription: s })}
              />
            ))}
          </ul>
        )}
      </section>

      {isAdmin && <AdminSubscriptionsTable categories={categories} />}
    </div>
  );
}

export default NewsletterSubscriptions;
