/** The detail pane's tabs, in display order. */
export type DetailTab = 'documents' | 'links' | 'bom' | 'workflow' | 'changelog';

export const DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: 'documents', label: 'Documents' },
  { key: 'links', label: 'Links' },
  { key: 'bom', label: 'BOM' },
  { key: 'workflow', label: 'Workflow' },
  { key: 'changelog', label: 'Changelog' },
];
