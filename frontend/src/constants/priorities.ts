export interface PriorityOption {
  value: string;
  label: string;
}

export const PRIORITIES: PriorityOption[] = [
  { value: 'high', label: 'Yüksek' },
  { value: 'med',  label: 'Orta' },
  { value: 'low',  label: 'Düşük' },
];
