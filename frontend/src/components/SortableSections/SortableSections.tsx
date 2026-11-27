import { useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react';
import type { SidebarSectionId } from '../../types';
import { moveSection } from '../../utils/sidebarOrder';
import './SortableSections.css';

export interface SortableSection {
  id: SidebarSectionId;
  /** Section title, used for the handle's accessible name ("… bölümünü taşı"). */
  label: string;
  content: ReactNode;
}

interface SortableSectionsProps {
  sections: SortableSection[];
  /** Every section id, in display order (see normalizeSidebarOrder). */
  order: SidebarSectionId[];
  onReorder: (order: SidebarSectionId[]) => void;
}

interface DropTarget {
  id: SidebarSectionId;
  after: boolean;
}

/** Sidebar sections the user reorders by dragging the ⠿ handle next to each one (native HTML5
 *  drag and drop), or with ↑ / ↓ while the handle has focus. Only the handle starts a drag, so
 *  clicking a header still opens/closes its section. */
function SortableSections({ sections, order, onReorder }: SortableSectionsProps) {
  const [dragged, setDragged] = useState<SidebarSectionId | null>(null);
  const [dropTarget, setDropTarget] = useState<DropTarget | null>(null);
  const sectionRefs = useRef<Partial<Record<SidebarSectionId, HTMLDivElement | null>>>({});
  const handleRefs = useRef<Partial<Record<SidebarSectionId, HTMLSpanElement | null>>>({});
  const byId = new Map(sections.map((s) => [s.id, s]));
  const visible = order.filter((id) => byId.has(id));

  const reset = () => {
    setDragged(null);
    setDropTarget(null);
  };

  const handleDragStart = (e: DragEvent, id: SidebarSectionId) => {
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', id); // Firefox only starts a drag with data set
    const section = sectionRefs.current[id];
    if (section) e.dataTransfer.setDragImage(section, 16, 16);
    setDragged(id);
  };

  const handleDragOver = (e: DragEvent<HTMLDivElement>, id: SidebarSectionId) => {
    if (!dragged) return; // not one of our sections (a file, a text selection…)
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    if (dropTarget?.id !== id || dropTarget.after !== after) setDropTarget({ id, after });
  };

  const handleDrop = (e: DragEvent, id: SidebarSectionId) => {
    e.preventDefault();
    if (dragged && dragged !== id) {
      const next = moveSection(order, dragged, id, dropTarget?.id === id ? dropTarget.after : false);
      if (next.join() !== order.join()) onReorder(next);
    }
    reset();
  };

  const handleKeyDown = (e: KeyboardEvent, id: SidebarSectionId) => {
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    e.preventDefault();
    const index = visible.indexOf(id);
    const neighbour = visible[e.key === 'ArrowUp' ? index - 1 : index + 1];
    if (!neighbour) return;
    onReorder(moveSection(order, id, neighbour, e.key === 'ArrowDown'));
    // The section re-renders in its new place: keep the focus on its handle for the next press.
    requestAnimationFrame(() => handleRefs.current[id]?.focus());
  };

  return (
    <div className="sortable-sections">
      {visible.map((id, index) => {
        const section = byId.get(id)!;
        const isTarget = dropTarget?.id === id && dragged !== id;
        const classes = [
          'sortable-section',
          dragged === id ? 'sortable-section--dragging' : '',
          isTarget ? (dropTarget.after ? 'sortable-section--drop-after' : 'sortable-section--drop-before') : '',
        ].filter(Boolean).join(' ');
        return (
          <div
            key={id}
            ref={(el) => { sectionRefs.current[id] = el; }}
            className={classes}
            data-section-id={id}
            onDragOver={(e) => handleDragOver(e, id)}
            onDragLeave={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null) && dropTarget?.id === id) setDropTarget(null);
            }}
            onDrop={(e) => handleDrop(e, id)}
          >
            <span
              ref={(el) => { handleRefs.current[id] = el; }}
              className="sortable-section-handle"
              role="button"
              tabIndex={0}
              draggable
              aria-label={`${section.label} bölümünü taşı (${index + 1}/${visible.length})`}
              title="Sürükleyerek ya da ↑ / ↓ tuşlarıyla taşıyın"
              onDragStart={(e) => handleDragStart(e, id)}
              onDragEnd={reset}
              onKeyDown={(e) => handleKeyDown(e, id)}
            >
              ⠿
            </span>
            <div className="sortable-section-content">{section.content}</div>
          </div>
        );
      })}
    </div>
  );
}

export default SortableSections;
