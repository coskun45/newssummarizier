/**
 * Minimal toast event bus. Mirrors the existing `auth:logout` window-event pattern used by the
 * axios interceptor, so showing a toast doesn't require threading a context/provider through
 * every component that fires a mutation.
 */

export type ToastVariant = 'error' | 'success' | 'info';

export interface ToastEventDetail {
    id: number;
    message: string;
    variant: ToastVariant;
}

let nextId = 1;

export function showToast(message: string, variant: ToastVariant = 'info') {
    const detail: ToastEventDetail = { id: nextId++, message, variant };
    window.dispatchEvent(new CustomEvent<ToastEventDetail>('toast:show', { detail }));
}

/** Extract a user-facing message from an axios/fetch error, falling back to a generic Turkish message. */
export function getErrorMessage(error: unknown, fallback = 'Bir hata oluştu. Lütfen tekrar deneyin.'): string {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) {
        return detail;
    }
    if ((error as { code?: string })?.code === 'ECONNABORTED') {
        return 'İstek zaman aşımına uğradı. Lütfen tekrar deneyin.';
    }
    if (error instanceof Error && error.message) {
        return fallback;
    }
    return fallback;
}
