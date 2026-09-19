import type { ReactNode } from 'react';
import { LockClosedIcon } from '@heroicons/react/24/outline';
import './PromptComposite.css';

interface PromptCompositeProps {
  /** The user-editable part (a textarea while editing, plain text otherwise). */
  editable: ReactNode;
  /**
   * The part the pipeline appends itself (topic list, output format): shown, never editable.
   * While it is still loading the frame is rendered without the locked section, so the editable
   * node keeps its place in the tree (no remount, no lost focus) when the text arrives.
   */
  lockedText?: string;
  /** Accessible name of the locked section; give each one a distinct name when a page has several. */
  lockedLabel?: string;
}

/**
 * The prompt exactly as the model receives it: the editable part on top, and directly below it —
 * in the same frame — the locked part that the application logic depends on.
 */
function PromptComposite({ editable, lockedText, lockedLabel = 'Kilitli sistem bölümü' }: PromptCompositeProps) {
  return (
    <div className="prompt-composite">
      <div className="prompt-composite-editable">{editable}</div>
      {lockedText && (
        <section className="prompt-composite-locked" aria-label={lockedLabel}>
          <div className="prompt-composite-locked-head">
            <LockClosedIcon aria-hidden="true" />
            <span>Sistem tarafından otomatik eklenir — uygulama mantığı buna dayanır, değiştirilemez</span>
          </div>
          <pre className="prompt-composite-locked-text" data-testid="locked-prompt-text">{lockedText}</pre>
        </section>
      )}
    </div>
  );
}

export default PromptComposite;
