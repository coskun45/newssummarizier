import { useState } from 'react';
import type {
  PlaygroundClassificationResult,
  PlaygroundRunResult,
  PlaygroundStageCall,
  PlaygroundSummaryResult,
} from '../../types';
import './PlaygroundResults.css';

const OUTCOME_LABELS: Record<PlaygroundClassificationResult['pipeline_outcome'], string> = {
  continue: 'Pipeline devam eder',
  filtered: 'Filtrelenir (önemsiz)',
  failed: 'Hata: haber "failed" olur',
};

const SKIPPED_LABELS: Record<NonNullable<PlaygroundRunResult['skipped_reason']>, string> = {
  unimportant: 'Haber önemsiz sınıflandırıldığı için özetleme atlandı (gerçek pipeline da atlar). "Yine de özetle" ile zorlayabilirsiniz.',
  classification_failed: 'Sınıflandırma başarısız olduğu için özetleme atlandı.',
};

const SOURCE_LABELS = { cleaned: 'temizlenmiş içerik', raw: 'ham RSS içeriği', none: 'içerik yok' } as const;
const PROMPT_SOURCE_LABELS = { override: 'değiştirilmiş', db: 'kayıtlı', default: 'varsayılan' } as const;

const formatCost = (cost: number) => `$${cost.toFixed(4)}`;
const formatLatency = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)} sn` : `${ms} ms`);

function Metrics({ call }: { call: PlaygroundStageCall }) {
  return (
    <dl className="playground-metrics">
      <div><dt>Model</dt><dd>{call.model}</dd></div>
      <div><dt>Prompt</dt><dd>{PROMPT_SOURCE_LABELS[call.prompt_source]}</dd></div>
      <div><dt>Token (giriş / çıkış)</dt><dd>{call.input_tokens} / {call.output_tokens}</dd></div>
      <div><dt>Maliyet</dt><dd>{formatCost(call.cost)}</dd></div>
      <div><dt>Süre</dt><dd>{formatLatency(call.latency_ms)}</dd></div>
      <div><dt>Sıcaklık / max token</dt><dd>{call.temperature} / {call.max_completion_tokens}</dd></div>
    </dl>
  );
}

function CallDetails({ call }: { call: PlaygroundStageCall }) {
  return (
    <div className="playground-call-details">
      <details>
        <summary>Sistem prompt'u (modele giden)</summary>
        <pre className="playground-pre">{call.system_prompt}</pre>
      </details>
      {call.attempts.map((attempt) => (
        <details key={attempt.attempt}>
          <summary>
            Deneme {attempt.attempt}
            {attempt.error ? ' — hata' : ''}
            {' · '}{formatLatency(attempt.latency_ms)}
            {attempt.finish_reason ? ` · ${attempt.finish_reason}` : ''}
          </summary>
          <p className="playground-detail-label">Kullanıcı prompt'u</p>
          <pre className="playground-pre">{attempt.user_prompt}</pre>
          <p className="playground-detail-label">Ham cevap</p>
          <pre className="playground-pre">{attempt.raw_response ?? '(boş)'}</pre>
          {attempt.error && <p className="playground-error">{attempt.error}</p>}
        </details>
      ))}
    </div>
  );
}

function ClassificationCard({ result }: { result: PlaygroundClassificationResult }) {
  return (
    <section className="playground-card" aria-label="Sınıflandırma sonucu">
      <h3 className="playground-card-title">Sınıflandırma</h3>
      {result.error && <p className="playground-error" role="alert">{result.error}</p>}

      <div className="playground-badges">
        <span className="badge playground-badge">Önem: {result.importance ?? '—'}</span>
        <span className="badge playground-badge">Öncelik: {result.priority ?? '—'}</span>
        <span className={`badge playground-badge playground-badge--${result.pipeline_outcome}`}>
          {OUTCOME_LABELS[result.pipeline_outcome]}
        </span>
      </div>

      {result.topics.length > 0 && (
        <ul className="playground-topics" aria-label="Konular">
          {result.topics.map((topic) => (
            <li key={topic.name} className={topic.known ? '' : 'playground-topic--unknown'}>
              {topic.name}
              {topic.confidence !== null && ` (${topic.confidence})`}
              {!topic.known && ' — sistemde yok, pipeline atlar'}
            </li>
          ))}
        </ul>
      )}

      <Metrics call={result} />
      <CallDetails call={result} />
    </section>
  );
}

function SummaryCard({ result }: { result: PlaygroundSummaryResult }) {
  return (
    <div className="playground-summary" role="tabpanel">
      {result.error && <p className="playground-error" role="alert">{result.error}</p>}
      {result.summary_text && <div className="playground-summary-text">{result.summary_text}</div>}
      <p className="playground-detail-label">Kullanılan talimat</p>
      <pre className="playground-pre">{result.instructions}</pre>
      <Metrics call={result} />
      <CallDetails call={result} />
    </div>
  );
}

interface PlaygroundResultsProps {
  result: PlaygroundRunResult;
}

function PlaygroundResults({ result }: PlaygroundResultsProps) {
  const [activeType, setActiveType] = useState<string | null>(null);
  const active = result.summaries.find((s) => s.summary_type === activeType) ?? result.summaries[0];

  return (
    <div className="playground-results">
      <div className="playground-results-head">
        <h2 className="playground-results-title">{result.article.title}</h2>
        <p className="playground-results-meta">
          {SOURCE_LABELS[result.content_used.source]} · {result.content_used.used_chars} / {result.content_used.chars} karakter
          {result.content_used.truncated && ' (kısaltıldı)'} · Son çalıştırma maliyeti {formatCost(result.total_cost)}
        </p>
      </div>

      {result.classification && <ClassificationCard result={result.classification} />}

      {result.skipped_reason && <p className="playground-notice">{SKIPPED_LABELS[result.skipped_reason]}</p>}

      {active && (
        <section className="playground-card" aria-label="Özet sonuçları">
          <h3 className="playground-card-title">Özetleme</h3>
          <div className="playground-tabs" role="tablist">
            {result.summaries.map((summary) => (
              <button
                key={summary.summary_type}
                type="button"
                role="tab"
                aria-selected={summary.summary_type === active.summary_type}
                className={`playground-tab${summary.summary_type === active.summary_type ? ' playground-tab--active' : ''}`}
                onClick={() => setActiveType(summary.summary_type)}
              >
                {summary.summary_type}
                {summary.error ? ' ⚠' : ''}
              </button>
            ))}
          </div>
          <SummaryCard result={active} />
        </section>
      )}
    </div>
  );
}

export default PlaygroundResults;
