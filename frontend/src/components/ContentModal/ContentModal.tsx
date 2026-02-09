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
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2 className="modal-title">{title}</h2>
          <button className="modal-close" onClick={onClose}>
            <XMarkIcon />
          </button>
        </div>
        <div className="modal-body">
          {content ? (
            <div className="content-text">
              {content.split('\n').map((paragraph, idx) => (
                paragraph.trim() && <p key={idx}>{paragraph}</p>
              ))}
            </div>
          ) : (
            <p className="text-muted">Kein Inhalt verfügbar</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default ContentModal;
