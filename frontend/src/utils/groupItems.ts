import type { ItemGroup } from '../types';
import { getErrorMessage } from '../lib/toast';

/** Name of the virtual group holding everything without a (known) group. */
export const OTHER_GROUP_LABEL = 'Diğer';

export interface ItemSection<T> {
  key: string;
  label: string;
  /** The real group, or null for the virtual "Diğer". */
  group: ItemGroup | null;
  items: T[];
}

/**
 * Split feeds/topics into sections: one per group (in the order the API returns them, i.e.
 * display_order), then "Diğer" for the rest — including members of a group that no longer exists.
 * Empty sections are skipped (sidebar) unless `includeEmpty` (Ayarlar, where a new group must show
 * up before it has members). With no groups at all it returns a single "Diğer" section, which
 * callers render as the plain, ungrouped list.
 */
export function groupItems<T extends { group_id?: number | null }>(
  items: T[],
  groups: ItemGroup[],
  { includeEmpty = false }: { includeEmpty?: boolean } = {},
): ItemSection<T>[] {
  const byGroup = new Map<number, T[]>(groups.map((g) => [g.id, []]));
  const other: T[] = [];
  for (const item of items) {
    const bucket = item.group_id != null ? byGroup.get(item.group_id) : undefined;
    (bucket ?? other).push(item);
  }
  const sections: ItemSection<T>[] = groups
    .map((g) => ({ key: `group-${g.id}`, label: g.name, group: g, items: byGroup.get(g.id) ?? [] }))
    .filter((s) => includeEmpty || s.items.length > 0);
  if (other.length > 0 || includeEmpty) {
    sections.push({ key: 'other', label: OTHER_GROUP_LABEL, group: null, items: other });
  }
  return sections;
}

/** Longest group name the API accepts. */
export const GROUP_NAME_MAX_LENGTH = 100;

/** User-facing message for a failed group create/rename/delete request. */
export function groupErrorText(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (detail === 'Group with this name already exists') return 'Bu adda bir grup zaten var.';
  // FastAPI validation error (422): detail is a list of {type, msg}
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { type?: string; msg?: string };
    if (first.type === 'string_too_long') return `Grup adı en fazla ${GROUP_NAME_MAX_LENGTH} karakter olabilir.`;
    // Our own validators ("Grup adı boş olamaz", '"Diğer" adı ayrılmıştır') come as "Value error, …"
    if (first.type === 'value_error' && first.msg) return first.msg.replace(/^Value error,\s*/, '');
    return fallback;
  }
  return getErrorMessage(err, fallback);
}
