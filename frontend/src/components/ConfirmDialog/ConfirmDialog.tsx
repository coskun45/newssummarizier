import { useEffect, useId, useRef } from 'react';
import { XMarkIcon } from '@heroicons/react/24/outline';
import './ConfirmDialog.css';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** While true the confirm button is disabled (the action is running). */
  pending?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** In-app replacement for the browser's confirm() — same modal shell as ContentModal. */
function ConfirmDialog({ isOpen, title, message, confirmLabel, cancelLabel = 'İptal', pending = false, onConfirm, onCancel }: ConfirmDialogProps) {
  const titleId = useId();
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isOpen) return;
    confirmRef.current?.focus();
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [isOpen, onCancel]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onCancel}>
      <div
        className="modal-shell confirm-dialog-shell"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-shell-header">
          <h2 id={titleId}>{title}</h2>
          <button className="modal-close-btn" onClick={onCancel} aria-label="Kapat">
            <XMarkIcon />
          </button>
        </div>
        <div className="modal-shell-body">
          <p className="confirm-dialog-message">{message}</p>
        </div>
        <div className="modal-shell-footer">
          <button className="btn btn-outline" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button ref={confirmRef} className="btn btn-primary" onClick={onConfirm} disabled={pending}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ConfirmDialog;
