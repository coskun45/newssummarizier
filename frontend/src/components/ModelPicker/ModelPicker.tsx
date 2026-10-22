import type { ReactNode } from 'react';
import { CheckCircleIcon } from '@heroicons/react/24/solid';
import type { ModelOption } from '../../types';
import './ModelPicker.css';

interface ModelPickerProps {
  /** Radio group name; also prefixes the option/tooltip ids. */
  name: string;
  label: string;
  hint: string;
  models: ModelOption[];
  /** The saved/selected model; null = the server default (nothing chosen). */
  value: string | null;
  /** Models the server uses while nothing is chosen (DEFAULT_MODEL / DETAILED_MODEL). */
  defaultIds: string[];
  /** null selects the server default, i.e. clears the choice. */
  onChange: (id: string | null) => void;
  disabled?: boolean;
}

const formatPrice = (usd: number) => `$${usd.toFixed(2)}`;

// Rough cost class from the output price, so the cards compare at a glance; exact prices are in
// the tooltip.
function costTier(model: ModelOption): string {
  if (model.output_per_1m <= 0.6) return '$';
  if (model.output_per_1m <= 2.5) return '$$';
  if (model.output_per_1m <= 5) return '$$$';
  return '$$$$';
}

function PriceRows({ model }: { model: ModelOption }) {
  return (
    <>
      <span className="model-option-tooltip-row">
        <span>Giriş</span><strong>{formatPrice(model.input_per_1m)}</strong>
      </span>
      <span className="model-option-tooltip-row">
        <span>Çıkış</span><strong>{formatPrice(model.output_per_1m)}</strong>
      </span>
    </>
  );
}

interface OptionCardProps {
  name: string;
  value: string;
  title: string;
  selected: boolean;
  onSelect: () => void;
  meta: ReactNode;
  tooltipId: string;
  tooltip: ReactNode;
  variant?: 'default';
}

function OptionCard({ name, value, title, selected, onSelect, meta, tooltipId, tooltip, variant }: OptionCardProps) {
  const classes = ['model-option'];
  if (selected) classes.push('model-option--selected');
  if (variant === 'default') classes.push('model-option--default');
  return (
    <label className={classes.join(' ')}>
      <input
        type="radio"
        className="model-option-input"
        name={name}
        value={value}
        checked={selected}
        onChange={onSelect}
        // Named by the title alone; the label also wraps the price tooltip, which is the description.
        aria-labelledby={`${tooltipId}-name`}
        aria-describedby={tooltipId}
      />
      <span className="model-option-head">
        <span className="model-option-name" id={`${tooltipId}-name`}>{title}</span>
        {selected && <CheckCircleIcon className="model-option-check" aria-hidden="true" />}
      </span>
      <span className="model-option-meta">{meta}</span>
      <span role="tooltip" id={tooltipId} className="model-option-tooltip">
        {tooltip}
        <span className="model-option-tooltip-unit">1M token başına (USD)</span>
      </span>
    </label>
  );
}

function ModelPicker({ name, label, hint, models, value, defaultIds, onChange, disabled = false }: ModelPickerProps) {
  const defaults = [...new Set(defaultIds)];
  const priceOf = (id: string) => models.find((m) => m.id === id);

  return (
    <fieldset className="model-picker" disabled={disabled}>
      <legend className="model-picker-legend">{label}</legend>
      <p className="model-picker-hint">{hint}</p>
      <div className="model-picker-grid">
        <OptionCard
          name={name}
          value=""
          title="Sunucu varsayılanı"
          selected={value === null}
          onSelect={() => onChange(null)}
          variant="default"
          meta={<span className="model-option-default-ids">{defaults.join(' / ')}</span>}
          tooltipId={`${name}-default-price`}
          tooltip={defaults.map((id) => {
            const model = priceOf(id);
            return (
              <span key={id} className="model-option-tooltip-group">
                {defaults.length > 1 && <span className="model-option-tooltip-model">{id}</span>}
                {model ? <PriceRows model={model} /> : <span>Fiyat bilgisi yok</span>}
              </span>
            );
          })}
        />
        {models.map((model) => (
          <OptionCard
            key={model.id}
            name={name}
            value={model.id}
            title={model.id}
            selected={model.id === value}
            onSelect={() => onChange(model.id)}
            meta={<span className="model-option-tier" aria-hidden="true">{costTier(model)}</span>}
            tooltipId={`${name}-${model.id}-price`}
            tooltip={<PriceRows model={model} />}
          />
        ))}
      </div>
    </fieldset>
  );
}

export default ModelPicker;
