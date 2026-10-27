import type { BulletinSummaryType } from '../types';

export interface BulletinSummaryOption {
  value: BulletinSummaryType;
  label: string;
  hint: string;
}

// Which summary a bulletin uses; shared by Bülten › Oluştur and the subscription form.
export const BULLETIN_SUMMARY_OPTIONS: BulletinSummaryOption[] = [
  { value: 'stored', label: 'Kayıtlı özet', hint: 'Haberin mevcut özeti kullanılır' },
  { value: 'detailed', label: 'Detaylı', hint: 'Birden fazla paragraf' },
  { value: 'standard', label: 'Standart', hint: 'Bir paragraf' },
  { value: 'brief', label: 'Kısa', hint: '2-3 cümle' },
];

export const DEFAULT_BULLETIN_SUMMARY_TYPE: BulletinSummaryType = 'stored';

export const BULLETIN_SUMMARY_HINT =
  'Haberin seçilen özeti yoksa üretilip kaydedilir. Kayıtlı özet: detaylı, yoksa standart, yoksa kısa.';
