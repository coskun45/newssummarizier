import { useEffect, useState } from 'react';
import { ChatBubbleLeftRightIcon, ExclamationTriangleIcon } from '@heroicons/react/24/outline';
import {
  useChatTools,
  useEmbeddingStatus,
  useSettings,
  useStartEmbeddingBackfill,
  useUpdateSettings,
} from '../../hooks/useApi';
import type { ChatToolName } from '../../types';
import './AssistantSettings.css';

interface AssistantSettingsProps {
  isAdmin: boolean;
}

/**
 * Ayarlar › Asistan: which tools the analysis agent may use, whether a plan waits for approval,
 * and the vector search index (how many articles are vectorized; admins start the backfill).
 */
function AssistantSettings({ isAdmin }: AssistantSettingsProps) {
  const { data: settings } = useSettings();
  const { data: tools, isLoading: toolsLoading } = useChatTools();
  const { data: embedding } = useEmbeddingStatus();
  const { mutate: updateSettings, isPending: saving, error: saveError } = useUpdateSettings();
  const { mutate: startBackfill, isPending: starting, error: backfillError } = useStartEmbeddingBackfill();

  const [enabled, setEnabled] = useState<Set<ChatToolName>>(new Set());
  const [requireApproval, setRequireApproval] = useState(false);
  const [saved, setSaved] = useState(false);

  // The switches start from the server state and are re-synced whenever it changes.
  useEffect(() => {
    if (tools) setEnabled(new Set(tools.filter((t) => t.enabled).map((t) => t.name)));
  }, [tools]);
  useEffect(() => {
    if (settings) setRequireApproval(settings.chat_require_plan_approval);
  }, [settings]);

  const usableDataToolOn = (tools ?? []).some((t) => t.data_tool && t.available && enabled.has(t.name));
  const storedEnabled = new Set((tools ?? []).filter((t) => t.enabled).map((t) => t.name));
  const dirty = !!tools && !!settings && (
    requireApproval !== settings.chat_require_plan_approval
    || storedEnabled.size !== enabled.size
    || [...enabled].some((name) => !storedEnabled.has(name))
  );

  const toggle = (name: ChatToolName) => {
    setSaved(false);
    setEnabled((current) => {
      const next = new Set(current);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const save = () => {
    updateSettings(
      { chat_enabled_tools: [...enabled].join(','), chat_require_plan_approval: requireApproval },
      { onSuccess: () => setSaved(true) },
    );
  };

  const job = embedding?.job;
  const running = job?.status === 'running';
  // Only what a backfill can embed: articles with no text at all (no page, no RSS text) never can.
  const embeddable = embedding ? embedding.summarized - embedding.no_text : 0;
  const missing = embedding ? Math.max(0, embeddable - embedding.embedded) : 0;

  return (
    <div className="settings-category assistant-settings">
      <h2 className="settings-content-title"><ChatBubbleLeftRightIcon className="section-icon" /> Asistan</h2>
      <p className="section-description">
        Asistan, haberler hakkındaki soruları gerekirse önce netleştirir, sonra bir analiz planı çıkarıp aşağıdaki
        araçlarla yürütür. Kapalı bir araç modele hiç verilmez.
      </p>
      {!isAdmin && <p className="section-description">Bu ayarları yalnızca yöneticiler değiştirebilir.</p>}

      <section className="assistant-section" aria-label="Araçlar">
        <h3 className="assistant-section-title">Araçlar</h3>
        {toolsLoading && <p className="section-description">Yükleniyor…</p>}
        <ul className="assistant-tools">
          {(tools ?? []).map((tool) => (
            <li key={tool.name} className={`assistant-tool${tool.available ? '' : ' assistant-tool--unavailable'}`}>
              <label className="assistant-tool-label">
                <input
                  type="checkbox"
                  checked={tool.available && enabled.has(tool.name)}
                  disabled={!isAdmin || !tool.available || saving}
                  onChange={() => toggle(tool.name)}
                />
                <span className="assistant-tool-name">{tool.label}</span>
                {tool.data_tool && <span className="badge assistant-tool-kind">veri aracı</span>}
              </label>
              <p className="assistant-tool-description">{tool.description}</p>
              {!tool.available && tool.unavailable_reason && (
                <p className="assistant-tool-reason">{tool.unavailable_reason}</p>
              )}
            </li>
          ))}
        </ul>
        {tools && !usableDataToolOn && (
          <p className="warning-text"><ExclamationTriangleIcon /> En az bir veri aracı (Veritabanı veya Vektör arama) açık kalmalı.</p>
        )}
      </section>

      <section className="assistant-section" aria-label="Plan onayı">
        <h3 className="assistant-section-title">Plan onayı</h3>
        <label className="assistant-tool-label">
          <input
            type="checkbox"
            checked={requireApproval}
            disabled={!isAdmin || saving}
            onChange={(e) => { setSaved(false); setRequireApproval(e.target.checked); }}
          />
          Analiz planını çalıştırmadan önce onay iste
        </label>
        <p className="assistant-tool-description">
          Açıkken asistan planı gösterip “Planı başlat” denmesini bekler; plan bir notla değiştirilebilir.
          Kapalıyken plan hemen yürütülür, “Durdur” ile kesilebilir.
        </p>
      </section>

      {isAdmin && (
        <div className="assistant-actions">
          <button type="button" className="btn btn-primary" onClick={save} disabled={!dirty || saving || !usableDataToolOn}>
            {saving ? 'Kaydediliyor…' : 'Kaydet'}
          </button>
          {saved && !dirty && <span className="assistant-saved" role="status">Kaydedildi.</span>}
          {saveError && <span className="warning-text" role="alert">Kaydedilemedi.</span>}
        </div>
      )}

      <section className="assistant-section" aria-label="Vektör arama">
        <h3 className="assistant-section-title">Vektör arama</h3>
        {embedding && !embedding.available && (
          <p className="warning-text"><ExclamationTriangleIcon /> {embedding.unavailable_reason}</p>
        )}
        {embedding && (
          <>
            <p className="assistant-embedding-stats">
              <strong>{embedding.embedded}</strong> / {embeddable} özetli haber vektörleştirildi
              ({embedding.chunks} metin parçası, {embedding.model}, {embedding.dimensions} boyut).
            </p>
            <p className="assistant-tool-description">
              Haberin sayfası çekilebildiyse tam metni, çekilemediyse (ödeme duvarı, robots.txt) RSS metni
              vektörleştirilir. Yeni haberler özetlendiğinde otomatik vektörleştirilir; önceden özetlenmiş
              haberler için toplu vektörleştirme başlatılabilir.
              {embedding.no_text > 0 && ` ${embedding.no_text} haberin hiç metni yok; bunlar aramaya dahil edilemez.`}
            </p>
            {running && job && (
              <div className="assistant-progress" role="status">
                <progress max={Math.max(job.total, 1)} value={job.done} />
                <span>Vektörleştiriliyor: {job.done} / {job.total}</span>
              </div>
            )}
            {job?.status === 'done' && job.total === 0 && !job.error && (
              <p className="assistant-tool-description" role="status">
                Son toplu işlem: vektörleştirilecek yeni haber yoktu.
              </p>
            )}
            {job?.status === 'done' && (job.total > 0 || job.error) && (
              <p className="assistant-tool-description" role="status">
                Son toplu işlem: {job.done - job.failed} haber vektörleştirildi
                {job.failed > 0 ? `, ${job.failed} başarısız` : ''} (maliyet ${job.cost.toFixed(4)}).
                {job.error ? ` Durdu: ${job.error}` : ''}
              </p>
            )}
            {isAdmin && (
              <button
                type="button"
                className="btn btn-outline"
                onClick={() => startBackfill()}
                disabled={!embedding.available || running || starting || missing <= 0}
              >
                {missing > 0 ? `Eksik ${missing} haberi vektörleştir` : 'Tüm haberler vektörleştirildi'}
              </button>
            )}
            {backfillError && <p className="warning-text" role="alert">Vektörleştirme başlatılamadı.</p>}
          </>
        )}
      </section>
    </div>
  );
}

export default AssistantSettings;
