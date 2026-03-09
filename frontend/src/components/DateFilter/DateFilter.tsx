import { useState } from 'react';
import type { DateFilterState } from '../../types';
import './DateFilter.css';

interface DateFilterSectionProps {
  title: string;
  value: DateFilterState;
  onChange: (val: DateFilterState) => void;
}

function DateFilterSection({ title, value, onChange }: DateFilterSectionProps) {
  const [open, setOpen] = useState(true);

  const setPreset = (preset: DateFilterState['preset']) => {
    onChange({ ...value, preset: value.preset === preset ? null : preset });
  };

  const isActive = value.preset !== null;

  return (
    <div className="date-filter-section">
      <button
        className={`importance-header header-date ${isActive ? 'active' : ''}`}
        onClick={() => setOpen(v => !v)}
      >
        <span className="importance-label">{title}</span>
        <span className="importance-chevron">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="importance-topics">
          {(['today', 'week', 'custom'] as const).map((preset) => (
            <label key={preset} className="topic-item">
              <input
                type="checkbox"
                checked={value.preset === preset}
                onChange={() => setPreset(preset)}
              />
              <span className="topic-name">
                {preset === 'today' ? 'Bugün' : preset === 'week' ? 'Son 1 Hafta' : 'Özel Tarih'}
              </span>
            </label>
          ))}

          {value.preset === 'custom' && (
            <div className="date-filter-custom">
              <div className="date-filter-row">
                <label className="date-filter-label">Başlangıç</label>
                <input
                  type="date"
                  className="date-filter-input"
                  value={value.customFrom}
                  onChange={e => onChange({ ...value, customFrom: e.target.value })}
                />
              </div>
              <div className="date-filter-row">
                <label className="date-filter-label">Bitiş</label>
                <input
                  type="date"
                  className="date-filter-input"
                  value={value.customTo}
                  onChange={e => onChange({ ...value, customTo: e.target.value })}
                />
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface DateFilterProps {
  publishedFilter: DateFilterState;
  onPublishedChange: (val: DateFilterState) => void;
  fetchedFilter: DateFilterState;
  onFetchedChange: (val: DateFilterState) => void;
}

function DateFilter({ publishedFilter, onPublishedChange, fetchedFilter, onFetchedChange }: DateFilterProps) {
  return (
    <div className="date-filter">
      <DateFilterSection
        title="Yayın Tarihi"
        value={publishedFilter}
        onChange={onPublishedChange}
      />
      <DateFilterSection
        title="İşlenme Tarihi"
        value={fetchedFilter}
        onChange={onFetchedChange}
      />
    </div>
  );
}

export default DateFilter;
