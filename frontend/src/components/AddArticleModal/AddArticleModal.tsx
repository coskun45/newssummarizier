import { useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import { XMarkIcon, ArrowPathIcon, CheckCircleIcon, DocumentArrowDownIcon } from '@heroicons/react/24/outline';
import { useCreateManualArticles, useFeeds, useReprocessStatus } from '../../hooks/useApi';
import { getErrorMessage } from '../../lib/toast';
import { downloadBlob } from '../../utils/downloadFile';
import {
  MANUAL_MAX_ARTICLES,
  MANUAL_MAX_FILE_BYTES,
  SAMPLE_MANUAL_JSON,
  checkManualArticle,
  parseManualJson,
  removeManualRows,
  type ParseResult,
} from '../../utils/manualArticles';
import type { ManualArticleInput, ManualArticlesResult } from '../../types';
import './AddArticleModal.css';

interface AddArticleModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Author names already seen in the list, offered as suggestions. */
  authorSuggestions?: string[];
}

type Tab = 'form' | 'json';

const SAMPLE_TEXT = JSON.stringify(SAMPLE_MANUAL_JSON, null, 2);

const emptyForm = { feedId: '', title: '', content: '', url: '', author: '', publishedAt: '', imageUrl: '' };

function AddArticleModal({ isOpen, onClose, authorSuggestions = [] }: AddArticleModalProps) {
  const [tab, setTab] = useState<Tab>('form');
  const [form, setForm] = useState(emptyForm);
  const [formProblems, setFormProblems] = useState<string[]>([]);
  const [jsonText, setJsonText] = useState('');
  const [fileError, setFileError] = useState<string | null>(null);
  const [result, setResult] = useState<ManualArticlesResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const { data: feeds = [] } = useFeeds();
  const createMutation = useCreateManualArticles();
  const { data: reprocessStatus } = useReprocessStatus();

  const parsed: ParseResult | null = useMemo(
    () => (jsonText.trim() ? parseManualJson(jsonText, feeds) : null),
    [jsonText, feeds],
  );
  const validJsonRows = parsed?.ok ? parsed.rows.filter((r) => r.problems.length === 0) : [];
  const invalidJsonCount = parsed?.ok ? parsed.rows.length - validJsonRows.length : 0;

  if (!isOpen) return null;

  const setField = (key: keyof typeof emptyForm) => (
    e: ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>,
  ) => setForm((prev) => ({ ...prev, [key]: e.target.value }));

  const submit = async (articles: ManualArticleInput[]) => {
    setSubmitError(null);
    setResult(null);
    try {
      const res = await createMutation.mutateAsync(articles);
      setResult(res);
      return res;
    } catch (err) {
      setSubmitError(getErrorMessage(err, 'Haberler eklenemedi.'));
      return null;
    }
  };

  const handleFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    const row = checkManualArticle({
      title: form.title,
      feed_id: form.feedId ? Number(form.feedId) : undefined,
      content: form.content,
      url: form.url,
      author: form.author,
      // datetime-local is local time; the backend wants an absolute ISO timestamp.
      published_at: form.publishedAt ? new Date(form.publishedAt).toISOString() : undefined,
      image_url: form.imageUrl,
    }, feeds);
    setFormProblems(row.problems);
    if (row.problems.length > 0) return;
    const res = await submit([row.input]);
    if (res && res.created.length > 0) setForm((prev) => ({ ...emptyForm, feedId: prev.feedId }));
  };

  const handleFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    setFileError(null);
    if (!file) return;
    if (file.size > MANUAL_MAX_FILE_BYTES) {
      setFileError('Dosya en fazla 2 MB olabilir.');
      return;
    }
    setJsonText(await file.text());
  };

  const handleJsonSubmit = async () => {
    if (!parsed?.ok) return;
    // Positions of the sent rows in the JSON list; `created[].index` points into the sent array.
    const sentIndexes = parsed.rows.flatMap((r, i) => (r.problems.length === 0 ? [i] : []));
    const res = await submit(sentIndexes.map((i) => parsed.rows[i].input));
    // Drop the created rows: sending the same text again must not create them a second time
    // (content-only rows get a fresh manual:// URL, so the URL duplicate check can't catch them).
    if (res && res.created.length > 0) {
      setJsonText(removeManualRows(jsonText, res.created.map((c) => sentIndexes[c.index])));
    }
  };

  const downloadSample = () => {
    downloadBlob(new Blob([SAMPLE_TEXT], { type: 'application/json' }), 'ornek-haberler.json');
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal-shell add-article-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-article-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-shell-header">
          <h2 id="add-article-title">Haber Ekle</h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Kapat">
            <XMarkIcon />
          </button>
        </div>

        <div className="modal-shell-body">
          <p className="add-article-intro text-muted">
            Eklenen haberler RSS haberleriyle aynı şekilde işlenir: sınıflandırılır, önceliklendirilir ve özetlenir.
          </p>

          <div className="add-article-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={tab === 'form'}
              className={`add-article-tab${tab === 'form' ? ' add-article-tab--active' : ''}`}
              onClick={() => setTab('form')}
            >
              Form
            </button>
            <button
              role="tab"
              aria-selected={tab === 'json'}
              className={`add-article-tab${tab === 'json' ? ' add-article-tab--active' : ''}`}
              onClick={() => setTab('json')}
            >
              JSON Yükle
            </button>
          </div>

          {tab === 'form' && (
            <form className="add-article-form" onSubmit={handleFormSubmit} noValidate>
              <label className="add-article-field">
                <span>Kaynak *</span>
                <select className="select" value={form.feedId} onChange={setField('feedId')} aria-label="Kaynak">
                  <option value="">Kaynak seçin…</option>
                  {feeds.map((f) => (
                    <option key={f.id} value={f.id}>{f.title || f.url}</option>
                  ))}
                </select>
              </label>
              <label className="add-article-field">
                <span>Başlık *</span>
                <input className="input" value={form.title} onChange={setField('title')} maxLength={500} aria-label="Başlık" />
              </label>
              <label className="add-article-field">
                <span>İçerik</span>
                <textarea
                  className="textarea"
                  rows={8}
                  value={form.content}
                  onChange={setField('content')}
                  maxLength={100000}
                  placeholder="Haberin tam metni. Boş bırakırsanız URL'deki sayfa çekilir."
                  aria-label="İçerik"
                />
              </label>
              <label className="add-article-field">
                <span>URL</span>
                <input className="input" type="url" value={form.url} onChange={setField('url')} placeholder="https://…" aria-label="URL" />
              </label>
              <div className="add-article-row">
                <label className="add-article-field">
                  <span>Yazar</span>
                  <input className="input" list="add-article-authors" value={form.author} onChange={setField('author')} maxLength={200} aria-label="Yazar" />
                  <datalist id="add-article-authors">
                    {authorSuggestions.map((a) => <option key={a} value={a} />)}
                  </datalist>
                </label>
                <label className="add-article-field">
                  <span>Yayın tarihi</span>
                  <input className="input" type="datetime-local" value={form.publishedAt} onChange={setField('publishedAt')} aria-label="Yayın tarihi" />
                </label>
              </div>
              <label className="add-article-field">
                <span>Görsel URL</span>
                <input className="input" type="url" value={form.imageUrl} onChange={setField('imageUrl')} placeholder="https://…" aria-label="Görsel URL" />
              </label>
              <p className="text-muted add-article-hint">* zorunlu. İçerik veya URL'den en az biri gerekli. Tarih boşsa şimdiki zaman kullanılır.</p>

              {formProblems.length > 0 && (
                <ul className="add-article-problems" role="alert">
                  {formProblems.map((p) => <li key={p}>{p}</li>)}
                </ul>
              )}

              <div className="add-article-actions">
                <button type="submit" className="btn btn-primary" disabled={createMutation.isPending}>
                  {createMutation.isPending ? 'Ekleniyor…' : 'Haberi Ekle'}
                </button>
              </div>
            </form>
          )}

          {tab === 'json' && (
            <div className="add-article-json">
              <div className="add-article-json-controls">
                <label className="btn btn-outline add-article-file">
                  JSON dosyası seç
                  <input type="file" accept=".json,application/json" onChange={handleFile} aria-label="JSON dosyası" />
                </label>
                <button type="button" className="btn btn-outline" onClick={downloadSample}>
                  <DocumentArrowDownIcon /> Örnek JSON indir
                </button>
              </div>
              {fileError && <p className="add-article-error" role="alert">{fileError}</p>}

              <label className="add-article-field">
                <span>JSON içeriği</span>
                <textarea
                  className="textarea add-article-json-text"
                  rows={8}
                  value={jsonText}
                  onChange={(e) => setJsonText(e.target.value)}
                  placeholder='{ "articles": [ … ] }'
                  aria-label="JSON içeriği"
                  spellCheck={false}
                />
              </label>

              {parsed && !parsed.ok && <p className="add-article-error" role="alert">{parsed.error}</p>}

              {parsed?.ok && (
                <div className="add-article-preview">
                  <h3>Önizleme ({parsed.rows.length} haber)</h3>
                  <table>
                    <thead>
                      <tr><th>#</th><th>Başlık</th><th>Kaynak</th><th>Durum</th></tr>
                    </thead>
                    <tbody>
                      {parsed.rows.map((row, i) => (
                        <tr key={i} className={row.problems.length ? 'add-article-preview-bad' : undefined}>
                          <td>{i + 1}</td>
                          <td>{row.input.title || '—'}</td>
                          <td>{row.feedLabel ?? row.input.feed ?? (row.input.feed_id != null ? `#${row.input.feed_id}` : '—')}</td>
                          <td>{row.problems.length ? row.problems.join(', ') : 'Hazır'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {invalidJsonCount > 0 && (
                    <p className="text-muted">{invalidJsonCount} hatalı kayıt gönderilmeyecek.</p>
                  )}
                </div>
              )}

              <div className="add-article-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleJsonSubmit}
                  disabled={createMutation.isPending || validJsonRows.length === 0}
                >
                  {createMutation.isPending ? 'Yükleniyor…' : `${validJsonRows.length} haberi yükle`}
                </button>
              </div>

              <details className="add-article-format">
                <summary>Geçerli JSON formatı</summary>
                <p>
                  Zorunlu: <code>title</code>, <code>feed</code> (kaynak adı) veya <code>feed_id</code>, ve{' '}
                  <code>content</code> ya da <code>url</code>. Opsiyonel: <code>author</code>,{' '}
                  <code>published_at</code> (ISO 8601; saat dilimi yoksa yerel saat), <code>image_url</code>. En fazla {MANUAL_MAX_ARTICLES} haber;
                  kök olarak doğrudan bir dizi de kabul edilir.
                </p>
                <pre>{SAMPLE_TEXT}</pre>
              </details>
            </div>
          )}

          {submitError && <p className="add-article-error" role="alert">{submitError}</p>}

          {result && (
            <div className="add-article-result" role="status">
              <p>
                <CheckCircleIcon /> {result.created.length} haber eklendi
                {result.skipped.length > 0 && `, ${result.skipped.length} atlandı`}
                {result.errors.length > 0 && `, ${result.errors.length} hatalı`}.
              </p>
              {[...result.skipped, ...result.errors].length > 0 && (
                <ul>
                  {[...result.skipped, ...result.errors].map((r) => (
                    <li key={`${r.index}-${r.reason}`}>{r.title}: {r.reason}</li>
                  ))}
                </ul>
              )}
              {result.queued > 0 && reprocessStatus?.status === 'running' && (
                <p className="add-article-progress">
                  <ArrowPathIcon className="spin-icon" /> İşleniyor: {reprocessStatus.done}/{reprocessStatus.total}
                </p>
              )}
              {result.queued > 0 && reprocessStatus?.status === 'done' && (
                <p className="add-article-progress">İşleme tamamlandı.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default AddArticleModal;
