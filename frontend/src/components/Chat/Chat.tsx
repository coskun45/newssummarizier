import { useEffect, useLayoutEffect, useRef, useState, type ComponentType, type FormEvent, type KeyboardEvent, type SVGProps } from 'react';
import { differenceInCalendarDays, formatDistanceToNow } from 'date-fns';
import { tr } from 'date-fns/locale';
import {
  ArrowDownIcon,
  ArrowPathIcon,
  ArrowTrendingUpIcon,
  ArrowUpIcon,
  ChartBarIcon,
  ChatBubbleLeftIcon,
  FireIcon,
  NewspaperIcon,
  PencilSquareIcon,
  SparklesIcon,
  StopIcon,
  TrashIcon,
} from '@heroicons/react/24/outline';
import {
  useArticleContent,
  useChatConversation,
  useChatConversations,
  useChatStream,
  useChatTools,
  useCreateChatConversation,
  useDeleteChatConversation,
} from '../../hooks/useApi';
import type { ChatConversation, ChatConversationSummary, ChatSendRequest } from '../../types';
import ChatRun from './ChatRun';
import ContentModal from '../ContentModal/ContentModal';
import ConfirmDialog from '../ConfirmDialog/ConfirmDialog';
import './Chat.css';

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

const EXAMPLE_QUESTIONS: { text: string; icon: Icon }[] = [
  { text: 'Son 7 günde konulara göre yüksek önemli haber sayıları nedir?', icon: ChartBarIcon },
  { text: 'Bu hafta öne çıkan yüksek önemli gelişmeleri özetle', icon: NewspaperIcon },
  { text: 'Ukrayna savaşıyla ilgili haberlerin önem dağılımı son bir ayda nasıl değişti?', icon: ArrowTrendingUpIcon },
  { text: 'Son 24 saatin en önemli 5 haberi hangileri?', icon: FireIcon },
];

/** Within this many pixels of the bottom the thread keeps following new output. */
const STICK_THRESHOLD = 80;
const MAX_LENGTH = 4000;

const GROUP_ORDER = ['Bugün', 'Dün', 'Son 7 gün', 'Son 30 gün', 'Daha eski'] as const;

function ArticleModal({ articleId, onClose }: { articleId: number; onClose: () => void }) {
  const { data, isLoading } = useArticleContent(articleId);
  return (
    <ContentModal
      isOpen
      onClose={onClose}
      title={data?.title ?? `Haber #${articleId}`}
      content={isLoading ? 'Yükleniyor…' : (data?.cleaned_content ?? data?.raw_content ?? null)}
    />
  );
}

function relativeTime(iso: string | null): string {
  return iso ? formatDistanceToNow(new Date(iso), { addSuffix: true, locale: tr }) : '';
}

/** The sidebar section a conversation is listed under, by its last activity. */
function groupOf(iso: string | null): (typeof GROUP_ORDER)[number] {
  if (!iso) return 'Daha eski';
  const days = differenceInCalendarDays(new Date(), new Date(iso));
  if (days <= 0) return 'Bugün';
  if (days === 1) return 'Dün';
  if (days < 7) return 'Son 7 gün';
  if (days < 30) return 'Son 30 gün';
  return 'Daha eski';
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Günaydın';
  if (hour < 18) return 'İyi günler';
  return 'İyi akşamlar';
}

/**
 * Asistan: questions about the news are clarified, planned and answered by the analysis agent.
 * The conversation list is on the left. With no conversation open the composer sits centered
 * under a greeting; once a conversation runs it docks under the thread, where the analysis
 * streams in live.
 */
interface ChatProps {
  /** False while another tab is shown: Chat stays mounted (a running stream survives) but hidden. */
  active?: boolean;
}

function Chat({ active = true }: ChatProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState('');
  const [openArticleId, setOpenArticleId] = useState<number | null>(null);
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);
  const [lastRequest, setLastRequest] = useState<{ body: ChatSendRequest; shownText: string } | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // Whether new output scrolls the thread; off while the user reads further up.
  const stickRef = useRef(true);

  const { data: conversations, isLoading: listLoading } = useChatConversations();
  const { data: conversation, isLoading: conversationLoading } = useChatConversation(selectedId);
  const { data: tools } = useChatTools();
  const { mutateAsync: createConversation, isPending: creating } = useCreateChatConversation();
  const { mutate: deleteConversation } = useDeleteChatConversation();
  const stream = useChatStream();

  const busy = stream.streaming || creating;
  const activeTools = (tools ?? []).filter((t) => t.active);
  const messages = conversation?.messages ?? [];
  const liveStored = stream.doneMessageId !== null && messages.some((m) => m.id === stream.doneMessageId);
  const showLive = !!stream.userText && !liveStored;
  const isEmpty = selectedId === null && !showLive;

  const scrollToEnd = () => {
    stickRef.current = true;
    setAtBottom(true);
    threadEndRef.current?.scrollIntoView?.({ block: 'end' });
  };

  useEffect(() => {
    if (stickRef.current) threadEndRef.current?.scrollIntoView?.({ block: 'end' });
  }, [conversation?.messages.length, stream.events.length, stream.tokens.length]);

  // Opening another conversation starts at its latest turn.
  useEffect(() => {
    stickRef.current = true;
    setAtBottom(true);
  }, [selectedId]);

  // The composer grows with its text up to its CSS max-height (also when it moves and remounts).
  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${el.scrollHeight}px`;
  }, [draft, isEmpty]);

  // The composer remounts when it moves between the welcome screen and the thread (and is hidden
  // while another tab is open); keep typing there.
  useEffect(() => {
    if (active) inputRef.current?.focus();
  }, [isEmpty, active]);

  // Esc stops a running analysis (unless the article reader is open — Esc closes that).
  const { streaming, stop } = stream;
  useEffect(() => {
    if (!streaming || !active || openArticleId !== null) return undefined;
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape') stop(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [streaming, stop, active, openArticleId]);

  const onThreadScroll = () => {
    const el = threadRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD;
    stickRef.current = near;
    setAtBottom(near);
  };

  const focusComposer = () => requestAnimationFrame(() => inputRef.current?.focus());

  const send = async (body: ChatSendRequest, shownText: string) => {
    if (busy) return;
    setLastRequest({ body, shownText });
    stickRef.current = true;
    let id = selectedId;
    if (id === null) {
      const created: ChatConversation = await createConversation(undefined);
      id = created.id;
      setSelectedId(id);
    }
    await stream.send(id, body, shownText);
  };

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    // While a plan waits for approval, a typed message is a change request for that plan.
    const action = conversation?.status === 'awaiting_plan_approval' ? 'approve_plan' : 'message';
    void send({ content: text, action }, text);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const lastAssistantIndex = messages.map((m) => m.role).lastIndexOf('assistant');
  const waitingFor = conversation?.status;
  const placeholder = waitingFor === 'awaiting_clarification'
    ? 'Soruyu cevaplayın veya kendi cevabınızı yazın…'
    : waitingFor === 'awaiting_plan_approval'
      ? 'Plan için değişiklik notu yazın ya da yukarıdan başlatın…'
      : 'Haberler hakkında bir analiz sorusu sorun…';
  const remaining = MAX_LENGTH - draft.length;

  const groups = GROUP_ORDER
    .map((label) => ({
      label,
      items: (conversations ?? []).filter((c) => groupOf(c.updated_at ?? c.created_at) === label),
    }))
    .filter((g) => g.items.length > 0);

  const startNew = () => {
    setSelectedId(null);
    setDraft('');
    focusComposer();
  };

  const retry = () => {
    if (!lastRequest) return;
    stream.clearError();
    void send(lastRequest.body, lastRequest.shownText);
  };

  const renderConversation = (c: ChatConversationSummary) => {
    const waiting = c.status === 'awaiting_clarification' || c.status === 'awaiting_plan_approval';
    return (
      <li key={c.id} className={`chat-conversation${c.id === selectedId ? ' chat-conversation--active' : ''}`}>
        <button
          type="button"
          className="chat-conversation-open"
          onClick={() => { setSelectedId(c.id); focusComposer(); }}
          disabled={busy && c.id !== selectedId}
          aria-current={c.id === selectedId ? 'true' : undefined}
          title={relativeTime(c.updated_at ?? c.created_at) || undefined}
        >
          <ChatBubbleLeftIcon className="chat-conversation-icon" />
          <span className="chat-conversation-text">
            <span className="chat-conversation-title">{c.title}</span>
            {waiting && (
              <span className="chat-conversation-meta chat-conversation-meta--waiting">
                {c.status === 'awaiting_clarification' ? 'Cevabınızı bekliyor' : 'Plan onayı bekliyor'}
              </span>
            )}
          </span>
        </button>
        <button
          type="button"
          className="btn-icon chat-conversation-delete"
          aria-label={`“${c.title}” sohbetini sil`}
          onClick={() => setPendingDelete(c.id)}
          disabled={busy && c.id === selectedId}
        >
          <TrashIcon />
        </button>
      </li>
    );
  };

  const composer = (
    <form className={`chat-composer${isEmpty ? ' chat-composer--hero' : ''}`} onSubmit={submit}>
      <div className="chat-composer-box">
        <textarea
          ref={inputRef}
          className="chat-input"
          rows={isEmpty ? 2 : 1}
          placeholder={placeholder}
          aria-label="Mesaj"
          aria-describedby="chat-composer-hint"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          maxLength={MAX_LENGTH}
        />
        <div className="chat-composer-toolbar">
          {activeTools.length > 0 && (
            <div className="chat-tools" aria-label="Açık araçlar">
              {activeTools.map((t) => <span key={t.name} className="chat-tool" title={t.description}>{t.label}</span>)}
            </div>
          )}
          <div className="chat-composer-actions">
            {remaining <= 500 && (
              <span className={remaining <= 100 ? 'chat-composer-count chat-composer-count--low' : 'chat-composer-count'}>
                {remaining} karakter kaldı
              </span>
            )}
            {stream.streaming ? (
              <button type="button" className="chat-send chat-send--stop" onClick={stream.stop} aria-label="Durdur" title="Durdur (Esc)">
                <StopIcon />
              </button>
            ) : (
              <button type="submit" className="chat-send" disabled={busy || !draft.trim()} aria-label="Gönder" title="Gönder (Enter)">
                <ArrowUpIcon />
              </button>
            )}
          </div>
        </div>
      </div>
      <p className="chat-composer-hint" id="chat-composer-hint">
        {stream.streaming
          ? 'Analiz sürüyor — sıradaki sorunuzu yazabilirsiniz · Esc ile durdurun'
          : 'Enter ile gönderin · Shift+Enter yeni satır · Asistan hata yapabilir, önemli bilgileri kaynaklardan kontrol edin.'}
      </p>
    </form>
  );

  return (
    <div className="chat">
      <aside className="chat-sidebar" aria-label="Sohbetler">
        <button type="button" className="chat-new" onClick={startNew} disabled={busy}>
          <PencilSquareIcon /> Yeni sohbet
        </button>
        <div className="chat-conversation-groups">
          {listLoading && <p className="chat-muted">Yükleniyor…</p>}
          {!listLoading && (conversations ?? []).length === 0 && <p className="chat-muted">Henüz sohbet yok.</p>}
          {groups.map((g) => (
            <section key={g.label} className="chat-conversation-group" aria-label={g.label}>
              <h3 className="chat-conversation-group-title">{g.label}</h3>
              <ul className="chat-conversations">{g.items.map(renderConversation)}</ul>
            </section>
          ))}
        </div>
      </aside>

      <section className={`chat-main${isEmpty ? ' chat-main--empty' : ''}`} aria-label="Asistan">
        {isEmpty ? (
          <div className="chat-welcome">
            <SparklesIcon className="chat-welcome-icon" />
            <h2 className="chat-welcome-title">{greeting()}</h2>
            <p className="chat-welcome-subtitle">Haberler hakkında ne öğrenmek istersiniz?</p>
            {composer}
            <div className="chat-examples" role="group" aria-label="Örnek sorular">
              {EXAMPLE_QUESTIONS.map(({ text, icon: ExampleIcon }) => (
                <button key={text} type="button" className="chat-example" onClick={() => { setDraft(text); focusComposer(); }}>
                  <ExampleIcon className="chat-example-icon" />
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            <header className="chat-header">
              <h2 className="chat-title">{conversation?.title ?? stream.userText ?? 'Asistan'}</h2>
            </header>

            <div className="chat-thread-wrap">
              <div className="chat-thread" ref={threadRef} onScroll={onThreadScroll}>
                {selectedId !== null && conversationLoading && !showLive && (
                  <div className="chat-loading" aria-label="Sohbet yükleniyor">
                    <div className="skeleton skeleton-line chat-loading-user" />
                    <div className="skeleton skeleton-line skeleton-line--title" />
                    <div className="skeleton skeleton-line skeleton-line--body" />
                    <div className="skeleton skeleton-line skeleton-line--body-short" />
                  </div>
                )}

                {messages.map((message, index) => (
                  message.role === 'user' ? (
                    <div key={message.id} className="chat-message chat-message--user">{message.content}</div>
                  ) : (
                    <div key={message.id} className="chat-message chat-message--assistant">
                      <ChatRun
                        events={message.events}
                        content={message.content}
                        cost={message.cost}
                        onArticleClick={setOpenArticleId}
                        clarification={index === lastAssistantIndex && waitingFor === 'awaiting_clarification' && !busy
                          ? { onAnswer: (text) => void send({ content: text, action: 'message' }, text), disabled: busy }
                          : null}
                        approval={index === lastAssistantIndex && waitingFor === 'awaiting_plan_approval' && !busy
                          ? {
                            onStart: () => void send({ content: '', action: 'approve_plan' }, 'Planı başlat'),
                            onRevise: (note) => void send({ content: note, action: 'approve_plan' }, note),
                            disabled: busy,
                          }
                          : null}
                      />
                    </div>
                  )
                ))}

                {showLive && (
                  <>
                    <div className="chat-message chat-message--user">{stream.userText}</div>
                    <div className="chat-message chat-message--assistant">
                      <ChatRun events={stream.events} liveText={stream.tokens} live onArticleClick={setOpenArticleId} />
                    </div>
                  </>
                )}

                {stream.error && (
                  <div className="chat-error chat-error--banner" role="alert">
                    <span className="chat-error-text">{stream.error}</span>
                    {lastRequest && (
                      <button type="button" className="btn btn-primary btn-sm" onClick={retry} disabled={busy}>
                        <ArrowPathIcon /> Tekrar dene
                      </button>
                    )}
                    <button type="button" className="btn btn-outline btn-sm" onClick={stream.clearError}>Kapat</button>
                  </div>
                )}
                <div ref={threadEndRef} />
              </div>
              {!atBottom && (
                <button type="button" className="chat-scroll-bottom" onClick={scrollToEnd} aria-label="En alta in" title="En alta in">
                  <ArrowDownIcon />
                </button>
              )}
            </div>

            {composer}
          </>
        )}
      </section>

      {openArticleId !== null && <ArticleModal articleId={openArticleId} onClose={() => setOpenArticleId(null)} />}

      <ConfirmDialog
        isOpen={pendingDelete !== null}
        title="Sohbeti sil"
        message="Bu sohbet ve tüm mesajları silinecek."
        confirmLabel="Sil"
        onConfirm={() => {
          if (pendingDelete !== null) {
            deleteConversation(pendingDelete);
            if (pendingDelete === selectedId) setSelectedId(null);
          }
          setPendingDelete(null);
        }}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}

export default Chat;
