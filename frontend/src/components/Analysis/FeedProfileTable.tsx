import type { AnalysisFeed } from '../../types';

interface FeedProfileTableProps {
  feeds: AnalysisFeed[];
}

const priorityKeys = ['high', 'med', 'low'] as const;

function FeedProfileTable({ feeds }: FeedProfileTableProps) {
  return (
    <div className="analysis-table-wrap">
      <table className="analysis-table">
        <thead>
          <tr>
            <th scope="col">Kaynak</th>
            <th scope="col" className="analysis-num">Haber</th>
            <th scope="col">Dağılım</th>
            <th scope="col" className="analysis-num">Yüksek oranı</th>
          </tr>
        </thead>
        <tbody>
          {feeds.map((feed) => (
            <tr key={feed.feed_id}>
              <th scope="row" className="analysis-feed-name">{feed.title}</th>
              <td className="analysis-num analysis-strong">{feed.total}</td>
              <td>
                <div
                  className="analysis-dist"
                  title={`${feed.high} yüksek, ${feed.med} orta, ${feed.low} düşük`}
                >
                  {priorityKeys.map((key) =>
                    feed[key] > 0 ? (
                      <span
                        key={key}
                        className={`analysis-dist-seg analysis-swatch--${key}`}
                        style={{ flexGrow: feed[key] }}
                      />
                    ) : null,
                  )}
                </div>
              </td>
              <td className="analysis-num">%{Math.round(feed.high_ratio * 100)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default FeedProfileTable;
