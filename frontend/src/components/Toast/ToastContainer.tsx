import { useEffect, useState } from 'react';
import { CheckCircleIcon, XCircleIcon, InformationCircleIcon } from '@heroicons/react/24/solid';
import type { ToastEventDetail, ToastVariant } from '../../lib/toast';
import './ToastContainer.css';

const AUTO_DISMISS_MS = 5000;

const ICONS: Record<ToastVariant, typeof CheckCircleIcon> = {
    success: CheckCircleIcon,
    error: XCircleIcon,
    info: InformationCircleIcon,
};

function ToastContainer() {
    const [toasts, setToasts] = useState<ToastEventDetail[]>([]);

    useEffect(() => {
        const handle = (event: Event) => {
            const detail = (event as CustomEvent<ToastEventDetail>).detail;
            setToasts((prev) => [...prev, detail]);
            setTimeout(() => {
                setToasts((prev) => prev.filter((t) => t.id !== detail.id));
            }, AUTO_DISMISS_MS);
        };
        window.addEventListener('toast:show', handle);
        return () => window.removeEventListener('toast:show', handle);
    }, []);

    const dismiss = (id: number) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    };

    if (toasts.length === 0) return null;

    return (
        <div className="toast-container" role="region" aria-live="polite">
            {toasts.map((toast) => {
                const Icon = ICONS[toast.variant];
                return (
                    <div
                        key={toast.id}
                        className={`toast toast--${toast.variant}`}
                        role="alert"
                        onClick={() => dismiss(toast.id)}
                    >
                        <Icon className="toast-icon" />
                        <span>{toast.message}</span>
                    </div>
                );
            })}
        </div>
    );
}

export default ToastContainer;
