import { ChevronLeftIcon, ChevronRightIcon } from '@heroicons/react/24/outline';
import './Pagination.css';

interface PaginationProps {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

// Build the list of page items to render, collapsing long runs with '...'.
function getPageItems(current: number, total: number): (number | 'left-ellipsis' | 'right-ellipsis')[] {
  const delta = 1; // pages shown on each side of the current page
  const items: (number | 'left-ellipsis' | 'right-ellipsis')[] = [];

  const start = Math.max(1, current - delta);
  const end = Math.min(total, current + delta);

  if (start > 1) {
    items.push(1);
    if (start > 2) items.push('left-ellipsis');
  }
  for (let p = start; p <= end; p++) items.push(p);
  if (end < total) {
    if (end < total - 1) items.push('right-ellipsis');
    items.push(total);
  }
  return items;
}

function Pagination({ currentPage, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null;

  const items = getPageItems(currentPage, totalPages);

  return (
    <nav className="pagination" aria-label="Sayfalama">
      <button
        className="pagination-btn pagination-nav"
        onClick={() => onPageChange(currentPage - 1)}
        disabled={currentPage <= 1}
        aria-label="Önceki sayfa"
      >
        <ChevronLeftIcon />
      </button>

      {items.map((item) =>
        item === 'left-ellipsis' || item === 'right-ellipsis' ? (
          <span key={item} className="pagination-ellipsis">…</span>
        ) : (
          <button
            key={item}
            className={`pagination-btn${item === currentPage ? ' pagination-btn--active' : ''}`}
            onClick={() => onPageChange(item)}
            aria-current={item === currentPage ? 'page' : undefined}
          >
            {item}
          </button>
        )
      )}

      <button
        className="pagination-btn pagination-nav"
        onClick={() => onPageChange(currentPage + 1)}
        disabled={currentPage >= totalPages}
        aria-label="Sonraki sayfa"
      >
        <ChevronRightIcon />
      </button>
    </nav>
  );
}

export default Pagination;
