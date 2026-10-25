import type { ArchiveDirection, Article } from '../../types';
import ArticleCard from '../ArticleCard/ArticleCard';
import './ArticleList.css';

interface ArticleListProps {
  articles: Article[];
  selectedIds?: Set<number>;
  onToggleSelect?: (id: number) => void;
  onSelectAll?: (ids: number[]) => void;
  onDeleted?: (id: number) => void;
  isArchiveView?: boolean;
  selectable?: boolean;
  canReprocess?: boolean;
  /** Enables each card's "Bu ve üstündekileri/altındakileri arşive gönder" menu. `offset` is the
   *  first article's position in the whole filtered list (page offset) and `total` that list's size,
   *  so each card knows how many articles "above"/"below" archives. */
  archiveRange?: {
    offset: number;
    total: number;
    onArchive: (article: Article, direction: ArchiveDirection, count: number) => void;
  };
}

function ArticleList({ articles, selectedIds = new Set(), onToggleSelect, onSelectAll: _onSelectAll, onDeleted, isArchiveView = false, selectable = false, canReprocess = false, archiveRange }: ArticleListProps) {

  return (
    <div className="article-list">
      {articles.map((article, index) => (
        <ArticleCard
          key={article.id}
          article={article}
          isSelected={selectedIds.has(article.id)}
          onToggleSelect={onToggleSelect}
          onDeleted={onDeleted}
          isArchiveView={isArchiveView}
          selectable={selectable}
          canReprocess={canReprocess}
          archiveRange={archiveRange && {
            aboveCount: archiveRange.offset + index + 1,
            belowCount: archiveRange.total - (archiveRange.offset + index),
            onArchive: archiveRange.onArchive,
          }}
        />
      ))}
    </div>
  );
}

export default ArticleList;
