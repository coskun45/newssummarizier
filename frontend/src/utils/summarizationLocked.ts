import type { PlaygroundSettings, PlaygroundSummaryType } from '../types';

/**
 * The read-only part of the summarization prompt for the given summary types: the heading, one
 * `type: instruction` line per type, and the fixed language line. Mirrors
 * `build_summarization_locked_text` in the backend, whose heading/language line it receives.
 *
 * `edits` are per-run instruction edits (Playground); a blank edit falls back to the default,
 * like the server does.
 */
export function buildSummarizationLockedText(
  locked: PlaygroundSettings['summarization_locked'],
  summaryTypes: PlaygroundSettings['summary_types'],
  selected: PlaygroundSummaryType[],
  edits: Partial<Record<PlaygroundSummaryType, string>> = {},
): string {
  const lines = [locked.heading, ''];
  const shown = summaryTypes.filter((info) => selected.includes(info.type));
  if (shown.length === 0) {
    lines.push('(özet türü seçilmedi)');
  } else {
    for (const info of shown) {
      lines.push(`${info.type}: ${edits[info.type]?.trim() ? edits[info.type] : info.default_instructions}`);
    }
  }
  lines.push('', locked.language_line);
  return lines.join('\n');
}
