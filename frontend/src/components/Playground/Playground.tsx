import { useRef, useState } from 'react';
import { useArticle, usePlaygroundSettings, useRunPlayground } from '../../hooks/useApi';
import type {
  PlaygroundRunRequest,
  PlaygroundRunResult,
  PlaygroundStage,
  PlaygroundSummaryType,
} from '../../types';
import PlaygroundArticlePicker from '../PlaygroundArticlePicker/PlaygroundArticlePicker';
import PlaygroundResults from '../PlaygroundResults/PlaygroundResults';
import PromptComposite from '../PromptComposite/PromptComposite';
import { buildSummarizationLockedText } from '../../utils/summarizationLocked';
import './Playground.css';

const CONTENT_PREVIEW_CHARS = 2000;

const PROMPT_SOURCE_LABELS = { db: 'kayıtlı prompt', default: 'varsayılan prompt' } as const;

type StatusTone = 'live' | 'edited' | 'empty';

// The server ignores blank prompts/instructions and uses the live ones, so the UI says so instead
// of implying an empty prompt was tested.
function promptStatus(
  text: string,
  dirty: boolean,
  source: keyof typeof PROMPT_SOURCE_LABELS,
): { label: string; tone: StatusTone } {
  if (!dirty) return { label: PROMPT_SOURCE_LABELS[source], tone: 'live' };
  return text.trim() === ''
    ? { label: 'boş — canlı prompt kullanılır', tone: 'empty' }
    : { label: 'değiştirildi', tone: 'edited' };
}

// Keep the results of stages that were not part of this run, so classification and
// summarization can be iterated on independently for the same article.
function mergeResult(
  prev: PlaygroundRunResult | null,
  next: PlaygroundRunResult,
  stages: PlaygroundStage[],
): PlaygroundRunResult {
  if (!prev || prev.article.id !== next.article.id) return next;
  const ranClassification = stages.includes('classification');
  const ranSummarization = stages.includes('summarization');
  return {
    ...next,
    classification: ranClassification ? next.classification : prev.classification,
    summaries: ranSummarization ? next.summaries : prev.summaries,
    skipped_reason: ranSummarization ? next.skipped_reason : ranClassification ? null : prev.skipped_reason,
  };
}

function Playground() {
  const [articleId, setArticleId] = useState<number | null>(null);
  const [promptEdits, setPromptEdits] = useState<{ classification?: string; summarization?: string }>({});
  const [instructionEdits, setInstructionEdits] = useState<Partial<Record<PlaygroundSummaryType, string>>>({});
  const [typeSelection, setTypeSelection] = useState<PlaygroundSummaryType[] | null>(null);
  const [forceSummarize, setForceSummarize] = useState(false);
  const [result, setResult] = useState<PlaygroundRunResult | null>(null);
  const selectedArticleRef = useRef<number | null>(null);

  const { data: settings, isLoading, isError, isFetching, refetch } = usePlaygroundSettings();
  const { data: article } = useArticle(articleId);
  const run = useRunPlayground();

  const handleSelect = (id: number) => {
    selectedArticleRef.current = id;
    setArticleId(id);
    setResult(null);
    run.reset();
  };

  if (isLoading) return <div className="playground-panel"><p>Yükleniyor…</p></div>;
  if (isError || !settings) return <div className="playground-panel"><p>Pipeline ayarları yüklenemedi.</p></div>;

  const classificationText = promptEdits.classification ?? settings.classification_prompt.text;
  const summarizationText = promptEdits.summarization ?? settings.summarization_prompt.text;
  const classificationDirty = classificationText !== settings.classification_prompt.text;
  const summarizationDirty = summarizationText !== settings.summarization_prompt.text;

  const selectedTypes = typeSelection ?? settings.summary_types.filter((t) => t.enabled).map((t) => t.type);
  const toggleType = (type: PlaygroundSummaryType) => {
    setTypeSelection(selectedTypes.includes(type) ? selectedTypes.filter((t) => t !== type) : [...selectedTypes, type]);
  };

  const canRunSummary = selectedTypes.length > 0;
  const busy = run.isPending;

  const systemTypes = settings.summary_types.filter((t) => t.enabled).map((t) => t.type);
  const typeSelectionDirty =
    selectedTypes.length !== systemTypes.length || selectedTypes.some((t) => !systemTypes.includes(t));
  const instructionsDirty = settings.summary_types.some((info) => {
    const edited = instructionEdits[info.type];
    return edited !== undefined && edited !== info.default_instructions;
  });
  const hasEdits = classificationDirty || summarizationDirty || instructionsDirty || typeSelectionDirty;

  // Back to what the pipeline uses right now: drop every edit and re-read the (possibly changed)
  // system settings, so "current" really is current.
  const handleResetAll = () => {
    setPromptEdits({});
    setInstructionEdits({});
    setTypeSelection(null);
    void refetch();
  };

  const summarizationLockedText = buildSummarizationLockedText(
    settings.summarization_locked,
    settings.summary_types,
    selectedTypes,
    instructionEdits,
  );
  const classificationStatus = promptStatus(classificationText, classificationDirty, settings.classification_prompt.source);
  const summarizationStatus = promptStatus(summarizationText, summarizationDirty, settings.summarization_prompt.source);

  const handleRun = (stages: PlaygroundStage[]) => {
    if (articleId === null) return;
    const instructions: PlaygroundRunRequest['summary_instructions'] = {};
    for (const info of settings.summary_types) {
      const edited = instructionEdits[info.type];
      if (selectedTypes.includes(info.type) && edited?.trim() && edited !== info.default_instructions) {
        instructions[info.type] = edited;
      }
    }
    // Only send prompts that were actually changed — otherwise the server uses the live setting.
    const request: PlaygroundRunRequest = {
      article_id: articleId,
      stages,
      classification_prompt: classificationDirty && classificationText.trim() ? classificationText : undefined,
      summarization_prompt: summarizationDirty && summarizationText.trim() ? summarizationText : undefined,
      summary_types: selectedTypes,
      summary_instructions: Object.keys(instructions).length > 0 ? instructions : undefined,
      force_summarize: forceSummarize || undefined,
    };
    run.mutate(request, {
      onSuccess: (next) => {
        if (selectedArticleRef.current !== next.article.id) return; // user moved on while it ran
        setResult((prev) => mergeResult(prev, next, stages));
      },
    });
  };

  const content = article ? (article.cleaned_content || article.raw_content || '') : '';

  return (
    <div className="playground-panel">
      <div className="playground-layout">
        <PlaygroundArticlePicker selectedId={articleId} onSelect={handleSelect} />

        <div className="playground-main">
          <section className="playground-section">
            <div className="playground-section-head">
              <div className="playground-section-intro">
                <h2 className="playground-section-title">Mevcut pipeline ayarları</h2>
                <p className="playground-section-description">
                  Sınıflandırma modeli <strong>{settings.classification_model}</strong>. Özet modelleri ve token limitleri
                  aşağıda. Model sunucu yapılandırmasından gelir ve burada değiştirilemez; prompt değişiklikleri yalnızca
                  bu çalıştırma için geçerlidir, kaydedilmez.
                </p>
              </div>
              <button
                type="button"
                className="btn btn-sm btn-outline playground-reset-all"
                disabled={!hasEdits || isFetching}
                onClick={handleResetAll}
                title="Prompt, talimat ve özet türü seçimini Ayarlar'daki güncel değerlere döndürür"
              >
                Sistem ayarlarına döndür
              </button>
            </div>

            <div className="playground-field">
              <div className="playground-field-head">
                <label htmlFor="playground-classification-prompt">Sınıflandırma sistem prompt'u</label>
                <span className="playground-field-meta">
                  <span className={`badge playground-status playground-status--${classificationStatus.tone}`}>
                    {classificationStatus.label}
                  </span>
                  {classificationDirty && (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline"
                      onClick={() => setPromptEdits((p) => ({ ...p, classification: undefined }))}
                    >
                      Sıfırla
                    </button>
                  )}
                </span>
              </div>
              <PromptComposite
                editable={(
                  <textarea
                    id="playground-classification-prompt"
                    className="textarea playground-prompt"
                    rows={8}
                    value={classificationText}
                    onChange={(e) => setPromptEdits((p) => ({ ...p, classification: e.target.value }))}
                  />
                )}
                lockedText={settings.classification_locked_text}
                lockedLabel="Kilitli sistem bölümü — sınıflandırma"
              />
              <p className="playground-hint">
                Konu listesi ({settings.topics.length} konu) ve JSON çıktı formatı her çalıştırmada otomatik eklenir; değiştirilemez.
              </p>
            </div>

            <div className="playground-field">
              <div className="playground-field-head">
                <label htmlFor="playground-summarization-prompt">Özetleme sistem prompt'u</label>
                <span className="playground-field-meta">
                  <span className={`badge playground-status playground-status--${summarizationStatus.tone}`}>
                    {summarizationStatus.label}
                  </span>
                  {summarizationDirty && (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline"
                      onClick={() => setPromptEdits((p) => ({ ...p, summarization: undefined }))}
                    >
                      Sıfırla
                    </button>
                  )}
                </span>
              </div>
              <PromptComposite
                editable={(
                  <textarea
                    id="playground-summarization-prompt"
                    className="textarea playground-prompt"
                    rows={8}
                    value={summarizationText}
                    onChange={(e) => setPromptEdits((p) => ({ ...p, summarization: e.target.value }))}
                  />
                )}
                lockedText={summarizationLockedText}
                lockedLabel="Kilitli sistem bölümü — özetleme"
              />
              <p className="playground-hint">
                İşaretli özet türlerinin talimatları ve dil satırı her özete otomatik eklenir; aşağıdaki özet türü
                seçimi ve talimat düzenlemeleri bu bloğa yansır.
              </p>
            </div>

            <fieldset className="playground-types">
              <legend>Özet türleri</legend>
              <div className="playground-types-grid">
                {settings.summary_types.map((info) => {
                  const checked = selectedTypes.includes(info.type);
                  const instructionValue = instructionEdits[info.type] ?? info.default_instructions;
                  return (
                    <div key={info.type} className={`playground-type${checked ? ' playground-type--checked' : ''}`}>
                      <label className="playground-type-label">
                        <input type="checkbox" checked={checked} onChange={() => toggleType(info.type)} />
                        <span>{info.type}</span>
                        <span className="playground-field-meta">
                          {info.model} · max {info.max_tokens} token{info.enabled ? '' : ' · pipeline\'da kapalı'}
                        </span>
                      </label>
                      {checked && (
                        <textarea
                          className="textarea"
                          rows={3}
                          aria-label={`${info.type} talimatı`}
                          value={instructionValue}
                          onChange={(e) => setInstructionEdits((p) => ({ ...p, [info.type]: e.target.value }))}
                        />
                      )}
                    </div>
                  );
                })}
              </div>
            </fieldset>
          </section>

          <section className="playground-section playground-run-bar">
            <h2 className="playground-section-title">Seçili haber</h2>
            {articleId === null && <p className="playground-hint">Soldan bir haber seçin.</p>}
            {article && (
              <>
                <p className="playground-article-title">
                  <a href={article.url} target="_blank" rel="noreferrer">{article.title}</a>
                </p>
                <details>
                  <summary>Özete giden içerik ({content.length} karakter)</summary>
                  <pre className="playground-content">
                    {content ? content.slice(0, CONTENT_PREVIEW_CHARS) + (content.length > CONTENT_PREVIEW_CHARS ? '…' : '') : '(içerik yok)'}
                  </pre>
                </details>
              </>
            )}

            <div className="playground-run-controls">
              <label className="playground-force">
                <input type="checkbox" checked={forceSummarize} onChange={(e) => setForceSummarize(e.target.checked)} />
                Haber önemsiz çıksa bile özetle
              </label>

              <div className="playground-actions">
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={articleId === null || busy}
                  onClick={() => handleRun(['classification'])}
                >
                  Sınıflandır
                </button>
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={articleId === null || busy || !canRunSummary}
                  onClick={() => handleRun(['summarization'])}
                >
                  Özetle
                </button>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={articleId === null || busy || !canRunSummary}
                  onClick={() => handleRun(['classification', 'summarization'])}
                >
                  {busy ? 'Çalışıyor…' : 'Tümünü çalıştır'}
                </button>
              </div>
            </div>
            {!canRunSummary && <p className="playground-hint">Özetlemek için en az bir özet türü seçin.</p>}
          </section>

          {result && <PlaygroundResults result={result} />}
        </div>
      </div>
    </div>
  );
}

export default Playground;
