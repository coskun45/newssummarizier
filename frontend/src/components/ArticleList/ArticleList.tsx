import type { Article } from '../../types';
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
}

function ArticleList({ articles, selectedIds = new Set(), onToggleSelect, onSelectAll: _onSelectAll, onDeleted, isArchiveView = false, selectable = false, canReprocess = false }: ArticleListProps) {

  return (
    <div className="article-list">
      {articles.map((article) => (
        <ArticleCard
          key={article.id}
          article={article}
          isSelected={selectedIds.has(article.id)}
          onToggleSelect={onToggleSelect}
          onDeleted={onDeleted}
          isArchiveView={isArchiveView}
          selectable={selectable}
          canReprocess={canReprocess}
        />
      ))}
    </div>
  );
}

export default ArticleList;
