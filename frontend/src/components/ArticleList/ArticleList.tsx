import type { Article } from '../../types';
import ArticleCard from '../ArticleCard/ArticleCard';
import './ArticleList.css';

interface ArticleListProps {
  articles: Article[];
  selectedIds?: Set<number>;
  onToggleSelect?: (id: number) => void;
  onSelectAll?: (ids: number[]) => void;
  isArchiveView?: boolean;
}

function ArticleList({ articles, selectedIds = new Set(), onToggleSelect, onSelectAll: _onSelectAll, isArchiveView = false }: ArticleListProps) {

  return (
    <div className="article-list">
      {articles.map((article) => (
        <ArticleCard
          key={article.id}
          article={article}
          isSelected={selectedIds.has(article.id)}
          onToggleSelect={onToggleSelect}
          isArchiveView={isArchiveView}
        />
      ))}
    </div>
  );
}

export default ArticleList;
