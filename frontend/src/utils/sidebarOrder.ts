import type { SidebarSectionId } from '../types';

/** The Haberler sidebar's sections, top to bottom, for a user who never reordered them. */
export const DEFAULT_SIDEBAR_ORDER: readonly SidebarSectionId[] = [
  'origin', 'feeds', 'priority', 'topics', 'published', 'fetched',
];

/** A stored order made usable: unknown and repeated ids dropped, sections it doesn't list yet
 *  (added after it was saved) appended in their default position order. */
export function normalizeSidebarOrder(stored: readonly string[] | null | undefined): SidebarSectionId[] {
  const known = new Set<string>(DEFAULT_SIDEBAR_ORDER);
  const seen = new Set<string>();
  const order: SidebarSectionId[] = [];
  for (const id of stored ?? []) {
    if (known.has(id) && !seen.has(id)) {
      seen.add(id);
      order.push(id as SidebarSectionId);
    }
  }
  return [...order, ...DEFAULT_SIDEBAR_ORDER.filter((id) => !seen.has(id))];
}

/** `order` with `moved` placed right before (`after` false) or after `target`. */
export function moveSection(
  order: readonly SidebarSectionId[], moved: SidebarSectionId, target: SidebarSectionId, after: boolean,
): SidebarSectionId[] {
  if (moved === target) return [...order];
  const rest = order.filter((id) => id !== moved);
  const index = rest.indexOf(target) + (after ? 1 : 0);
  return [...rest.slice(0, index), moved, ...rest.slice(index)];
}
