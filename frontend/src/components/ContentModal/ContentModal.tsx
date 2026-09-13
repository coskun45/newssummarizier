import { XMarkIcon } from '@heroicons/react/24/outline';
import './ContentModal.css';

interface ContentModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  content: string | null;
}

function ContentModal({ isOpen, onClose, title, content }: ContentModalProps) {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-shell content-modal-shell" onClick={(e) => e.stopPropagation()}>
        <div className="modal-shell-header">
          <h2>{title}</h2>
          <button className="modal-close-btn" onClick={onClose} aria-label="Kapat">
            <XMarkIcon />
          </button>
        </div>
        <div className="modal-shell-body">
          {content ? (
            <div className="content-text">
              {content.split('\n').map((paragraph, idx) => (
                paragraph.trim() && <p key={idx}>{paragraph}</p>
              ))}
            </div>
          ) : (
            <p className="text-muted content-empty">İçerik mevcut değil</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default ContentModal;
