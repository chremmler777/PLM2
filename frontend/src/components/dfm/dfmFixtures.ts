/**
 * Test fixtures: the full relay from the API contract (toolmaker original to
 * KTX, KTX forward to Tier 1, Tier 1 answer, KTX answer, toolmaker question).
 */
import type { DfmEntry, DfmTopicDetail, DfmTopicSummary } from '../../api/dfm';

export const makeEntry = (over: Partial<DfmEntry>): DfmEntry => ({
  id: 1, topic_id: 1, party: 'toolmaker', addressed_to: ['ktx'], note: null, kind: 'original', reply_to_id: null,
  answered_by: [], awaiting: [], sent_at: '2026-09-13', supersedes_id: null, recorded_by: 2,
  recorded_by_name: 'Christoph Demmler', recorded_at: '2026-09-23T22:13:13', files: [], history: [], ...over,
});

export const relayEntries = (): DfmEntry[] => [
  makeEntry({ id: 1, note: 'DFM rev 1', answered_by: [{ party: 'ktx', entry_id: 4, date: '2026-09-20' }],
    files: [{ id: 41, entry_id: 1, original_filename: 'dfm_rev1.pdf', file_size: 10, content_type: 'application/pdf', uploaded_by: 2, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-13T10:00:00' },
      { id: 42, entry_id: 1, original_filename: 'volumes.xlsx', file_size: 10, content_type: 'application/vnd.ms-excel', uploaded_by: 2, uploaded_by_name: 'Christoph Demmler', uploaded_at: '2026-09-13T10:00:00' }] }),
  makeEntry({ id: 2, party: 'ktx', addressed_to: ['tier1'], note: 'please check gate', kind: 'forward', reply_to_id: 1,
    answered_by: [{ party: 'tier1', entry_id: 3, date: '2026-09-18' }], sent_at: '2026-09-15' }),
  makeEntry({ id: 3, party: 'tier1', addressed_to: ['ktx'], note: 'gate ok', kind: 'answer', reply_to_id: 2, sent_at: '2026-09-18' }),
  makeEntry({ id: 4, party: 'ktx', addressed_to: ['toolmaker'], note: 'accepted by Tier 1', kind: 'answer', reply_to_id: 1, sent_at: '2026-09-20',
    recorded_by_name: 'Karl Huber' }),
  makeEntry({ id: 5, note: 'and the rib?', kind: 'question', reply_to_id: 4, awaiting: [{ party: 'ktx', days: 1 }], sent_at: '2026-09-22' }),
];

export const relaySummary = (over: Partial<DfmTopicSummary> = {}): DfmTopicSummary => ({
  id: 1, tool_part_id: 7, title: 'Gate position', status: 'open', opened_by: 2, opened_at: '2026-09-23T22:13:13',
  closed_by: null, closed_at: null, entry_count: 5, last_activity: '2026-09-23T22:13:14',
  waiting_on: [{ party: 'ktx', count: 1, oldest_days: 1 }],
  last_step: { kind: 'question', party: 'toolmaker', addressed_to: ['ktx'], date: '2026-09-22' },
  all_answered: false, ...over,
});

export const relayTopic = (over: Partial<DfmTopicDetail> = {}): DfmTopicDetail => ({
  ...relaySummary(), next_step: { entry_id: 5, kind: 'question', from: 'toolmaker', to: 'ktx', days: 1 },
  entries: relayEntries(), ...over,
});
