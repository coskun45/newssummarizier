import { useMemo, useState } from 'react';
import {
  CheckCircleIcon,
  ExclamationTriangleIcon,
  MinusCircleIcon,
  ArrowPathIcon,
  CheckIcon,
  ClipboardDocumentIcon,
  ClockIcon,
  ChevronRightIcon,
} from '@heroicons/react/24/outline';
import type { ChatChartSpec, ChatEvent, ChatPlanStep, ChatQuestion, ChatStepStatus } from '../../types';
import ChatChart from './ChatChart';
import ChatMarkdown from './ChatMarkdown';

/** Turkish names of the agent's tools, by catalog name and by function name. */
const TOOL_LABELS: Record<string, string> = {
  time: 'Zaman tespiti', resolve_time_range: 'Zaman tespiti',
  sql: 'Veritabanı (SQL)', run_sql: 'Veritabanı (SQL)',
  semantic_search: 'Vektör arama',
  chart: 'Grafik', render_chart: 'Grafik',
  python: 'Code interpreter', web_search: 'Web arama',
  none: 'Değerlendirme',
};

const STATUS_LABELS: Record<ChatStepStatus, string> = {
  pending: 'Bekliyor', running: 'Çalışıyor', done: 'Tamamlandı', failed: 'Başarısız', skipped: 'Atlandı',
};

interface ToolTrace {
  callId: string;
  name: string;
  input: string;
  ok?: boolean;
  summary?: string;
  sql?: string | null;
}

interface RunView {
  phase: Extract<ChatEvent, { type: 'phase' }> | null;
  intent: Extract<ChatEvent, { type: 'intent' }> | null;
  clarification: Extract<ChatEvent, { type: 'clarification' }> | null;
  steps: ChatPlanStep[];
  replanReason: string | null;
  awaitingApproval: boolean;
  traces: Record<number, ToolTrace[]>;
  charts: ChatChartSpec[];
  tokens: string;
  error: string | null;
  stopped: boolean;
}

function describeInput(name: string, raw: string): string {
  try {
    const args = JSON.parse(raw || '{}');
    if (name === 'run_sql') return args.query ?? '';
    if (name === 'resolve_time_range') return args.expression ?? '';
    if (name === 'semantic_search') return args.query ?? '';
    if (name === 'render_chart') return args.title ?? '';
    return raw;
  } catch {
    return raw;
  }
}

/** Fold a run's events into what the UI shows: the latest plan with each step's live status. */
function deriveRun(events: ChatEvent[]): RunView {
  const view: RunView = {
    phase: null, intent: null, clarification: null, steps: [], replanReason: null, awaitingApproval: false,
    traces: {}, charts: [], tokens: '', error: null, stopped: false,
  };
  const byCall: Record<string, ToolTrace> = {};
  const setStep = (id: number, patch: Partial<ChatPlanStep>) => {
    view.steps = view.steps.map((s) => (s.id === id ? { ...s, ...patch } : s));
  };
  for (const event of events) {
    switch (event.type) {
      case 'phase': view.phase = event; break;
      case 'intent': view.intent = event; break;
      case 'clarification': view.clarification = event; break;
      case 'plan': view.steps = event.steps; view.awaitingApproval = false; break;
      case 'plan_approval': view.steps = event.steps; view.awaitingApproval = true; break;
      case 'replan': view.steps = event.steps; view.replanReason = event.reason || null; break;
      case 'step_started': view.awaitingApproval = false; setStep(event.step_id, { status: 'running' }); break;
      case 'step_result': setStep(event.step_id, { status: event.status, finding: event.finding }); break;
      case 'tool_call': {
        const trace: ToolTrace = { callId: event.call_id, name: event.name, input: describeInput(event.name, event.arguments) };
        byCall[event.call_id] = trace;
        (view.traces[event.step_id] ??= []).push(trace);
        break;
      }
      case 'tool_result': {
        const trace = byCall[event.call_id];
        if (trace) Object.assign(trace, { ok: event.ok, summary: event.summary, sql: event.sql });
        break;
      }
      case 'chart': view.charts.push(event.chart); break;
      case 'token': view.tokens += event.text; break;
      case 'error': view.error = event.message; break;
      case 'stopped': view.stopped = true; break;
    }
  }
  return view;
}

function StepIcon({ status }: { status: ChatStepStatus }) {
  if (status === 'done') return <CheckCircleIcon className="chat-step-icon chat-step-icon--done" />;
  if (status === 'failed') return <ExclamationTriangleIcon className="chat-step-icon chat-step-icon--failed" />;
  if (status === 'skipped') return <MinusCircleIcon className="chat-step-icon chat-step-icon--skipped" />;
  if (status === 'running') return <ArrowPathIcon className="chat-step-icon chat-step-icon--running" />;
  return <ClockIcon className="chat-step-icon chat-step-icon--pending" />;
}

interface ClarificationCardProps {
  questions: ChatQuestion[];
  restatement: string;
  interactive: boolean;
  disabled: boolean;
  onAnswer: (text: string) => void;
}

function ClarificationCard({ questions, restatement, interactive, disabled, onAnswer }: ClarificationCardProps) {
  const [choices, setChoices] = useState<Record<number, string>>({});
  const [note, setNote] = useState('');
  const answered = questions.filter((_, i) => choices[i]).length;
  const canSend = interactive && !disabled && (answered > 0 || note.trim().length > 0);

  const send = () => {
    const parts = questions
      .map((q, i) => (choices[i] ? (questions.length > 1 ? `${q.question} ${choices[i]}` : choices[i]) : null))
      .filter(Boolean) as string[];
    if (note.trim()) parts.push(note.trim());
    onAnswer(parts.join('\n'));
  };

  return (
    <section className="chat-card chat-clarification" aria-label="Netleştirme soruları">
      {restatement && <p className="chat-card-lead">{restatement}</p>}
      {questions.map((q, i) => (
        <div key={i} className="chat-question">
          <p className="chat-question-text">{q.question}</p>
          {q.options.length > 0 && (
            <div className="chat-chips" role="group" aria-label={q.question}>
              {q.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`chat-chip${choices[i] === option ? ' chat-chip--selected' : ''}`}
                  aria-pressed={choices[i] === option}
                  disabled={!interactive || disabled}
                  onClick={() => setChoices((c) => ({ ...c, [i]: c[i] === option ? '' : option }))}
                >
                  {option}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
      {interactive && (
        <div className="chat-card-actions">
          <input
            className="input"
            placeholder="İsterseniz kendi cevabınızı yazın"
            aria-label="Netleştirme cevabı"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && canSend) { e.preventDefault(); send(); } }}
            disabled={disabled}
          />
          <button type="button" className="btn btn-primary btn-sm" disabled={!canSend} onClick={send}>
            Cevapla
          </button>
        </div>
      )}
    </section>
  );
}

interface PlanCardProps {
  steps: ChatPlanStep[];
  traces: Record<number, ToolTrace[]>;
  replanReason: string | null;
  approval: { onStart: () => void; onRevise: (note: string) => void; disabled: boolean } | null;
  onArticleClick: (articleId: number) => void;
}

function PlanCard({ steps, traces, replanReason, approval, onArticleClick }: PlanCardProps) {
  const [note, setNote] = useState('');
  const finished = steps.filter((s) => s.status !== 'pending' && s.status !== 'running').length;
  const started = steps.some((s) => s.status !== 'pending');
  const canRevise = !!approval && !approval.disabled && !!note.trim();
  return (
    <section className="chat-card chat-plan" aria-label="Analiz planı">
      <div className="chat-plan-header">
        <h4 className="chat-card-title">Analiz planı</h4>
        {started && (
          <span className="chat-plan-progress">
            {finished}/{steps.length} adım
            <span className="chat-plan-bar" aria-hidden="true">
              <span style={{ width: `${(finished / steps.length) * 100}%` }} />
            </span>
          </span>
        )}
      </div>
      {replanReason && <p className="chat-card-note">Plan güncellendi: {replanReason}</p>}
      <ol className="chat-steps">
        {steps.map((step) => (
          <li key={step.id} className={`chat-step chat-step--${step.status}`}>
            <div className="chat-step-head">
              <StepIcon status={step.status} />
              <span className="chat-step-goal">{step.goal}</span>
              <span className="chat-step-tool">{TOOL_LABELS[step.tool] ?? step.tool}</span>
              <span className="chat-sr-only">{STATUS_LABELS[step.status]}</span>
            </div>
            {step.finding && step.status !== 'running' && (
              <div className="chat-step-finding"><ChatMarkdown text={step.finding} onArticleClick={onArticleClick} /></div>
            )}
            {(traces[step.id] ?? []).length > 0 && (
              <details className="chat-trace">
                <summary>
                  <ChevronRightIcon className="chat-trace-chevron" />
                  Araç çağrıları ({traces[step.id].length})
                </summary>
                <ul>
                  {traces[step.id].map((trace) => (
                    <li key={trace.callId} className={trace.ok === false ? 'chat-trace-item chat-trace-item--failed' : 'chat-trace-item'}>
                      <span className="chat-trace-tool">{TOOL_LABELS[trace.name] ?? trace.name}</span>
                      {trace.summary && <span className="chat-trace-summary">{trace.summary}</span>}
                      {(trace.sql || trace.input) && <pre className="chat-trace-input">{trace.sql || trace.input}</pre>}
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </li>
        ))}
      </ol>
      {approval && (
        <div className="chat-card-actions chat-plan-approval">
          <button type="button" className="btn btn-primary btn-sm" onClick={approval.onStart} disabled={approval.disabled}>
            Planı başlat
          </button>
          <input
            className="input"
            placeholder="Plan için değişiklik notu (ör. sadece yüksek önemli haberler)"
            aria-label="Plan değişiklik notu"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && canRevise) { e.preventDefault(); approval.onRevise(note.trim()); } }}
            disabled={approval.disabled}
          />
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() => approval.onRevise(note.trim())}
            disabled={!canRevise}
          >
            Planı değiştir
          </button>
        </div>
      )}
    </section>
  );
}

interface ChatRunProps {
  events: ChatEvent[];
  /** The stored message text (report); while live the streamed tokens are shown instead. */
  content?: string | null;
  live?: boolean;
  /** While live: the report text streamed so far (tokens are kept out of `events`). */
  liveText?: string;
  /** The stored turn's OpenAI cost (USD). */
  cost?: number | null;
  onArticleClick: (articleId: number) => void;
  /** Set when this run's clarifying questions can still be answered. */
  clarification?: { onAnswer: (text: string) => void; disabled: boolean } | null;
  /** Set when this run's plan waits for approval. */
  approval?: { onStart: () => void; onRevise: (note: string) => void; disabled: boolean } | null;
}

/** One assistant turn: what the agent understood, its plan and tool calls, charts and the report. */
function ChatRun({ events, content = null, live = false, liveText = '', cost = null, onArticleClick, clarification = null, approval = null }: ChatRunProps) {
  const view = useMemo(() => deriveRun(events), [events]);
  // A stored turn's text repeats what its cards already show for a question, a plan waiting for
  // approval, an error or a stop — show it only when it is the report.
  const storedIsReport = !(view.clarification || view.awaitingApproval || view.error || view.stopped);
  const report = live ? liveText || view.tokens : (storedIsReport ? (content ?? '') : '');
  const shownCost = live ? null : cost;
  const showPhase = live && view.phase && !report;
  const [copied, setCopied] = useState(false);

  const copyReport = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="chat-run">
      {showPhase && view.phase && (
        <div className="chat-phase" role="status">
          <ArrowPathIcon className="chat-phase-icon" />
          {view.phase.label}
          {view.phase.phase === 'executing' && view.phase.step ? ` (${view.phase.step}/${view.phase.total})` : ''}…
        </div>
      )}

      {view.intent && (
        <div className="chat-intent">
          <span className="chat-intent-label">Anlaşılan amaç:</span> {view.intent.restatement}
          {view.intent.time_range && <span className="chat-intent-range"> · {view.intent.time_range.label}</span>}
          {view.intent.assumptions.length > 0 && (
            <ul className="chat-intent-assumptions">
              {view.intent.assumptions.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
        </div>
      )}

      {view.clarification && (
        <ClarificationCard
          questions={view.clarification.questions}
          restatement={view.clarification.restatement}
          interactive={!!clarification}
          disabled={clarification?.disabled ?? true}
          onAnswer={clarification?.onAnswer ?? (() => undefined)}
        />
      )}

      {view.steps.length > 0 && (
        <PlanCard
          steps={view.steps}
          traces={view.traces}
          replanReason={view.replanReason}
          approval={view.awaitingApproval ? approval : null}
          onArticleClick={onArticleClick}
        />
      )}

      {view.charts.map((chart) => <ChatChart key={chart.id} chart={chart} />)}

      {report && (
        <div className={live && !view.error && !view.stopped ? 'chat-report chat-report--streaming' : 'chat-report'}>
          <ChatMarkdown text={report} onArticleClick={onArticleClick} />
        </div>
      )}

      {view.error && (
        <p className="chat-error" role="alert"><ExclamationTriangleIcon /> {view.error}</p>
      )}
      {view.stopped && <p className="chat-card-note">Analiz durduruldu.</p>}
      {!live && (report || (shownCost !== null && shownCost > 0)) && (
        <div className="chat-run-footer">
          {report && (
            <button
              type="button"
              className={`chat-copy${copied ? ' chat-copy--copied' : ''}`}
              onClick={() => void copyReport()}
            >
              {copied ? <CheckIcon /> : <ClipboardDocumentIcon />}
              {copied ? 'Kopyalandı' : 'Raporu kopyala'}
            </button>
          )}
          {shownCost !== null && shownCost > 0 && (
            <span className="chat-cost">Maliyet: ${shownCost.toFixed(4)}</span>
          )}
        </div>
      )}
    </div>
  );
}

export default ChatRun;
