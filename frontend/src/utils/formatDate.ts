import { formatDistanceToNow } from 'date-fns';
import { tr } from 'date-fns/locale';

/** Formats a published-at timestamp as a relative time (e.g. "3 saat önce").
 * Guards against clock skew between the feed/server and the browser - a
 * just-published article should never render as being in the future. */
export function formatPublishedAt(publishedAt: string): string {
    const publishedDate = new Date(publishedAt);
    if (publishedDate.getTime() > Date.now()) {
        return 'az önce';
    }
    return formatDistanceToNow(publishedDate, { addSuffix: true, locale: tr });
}
