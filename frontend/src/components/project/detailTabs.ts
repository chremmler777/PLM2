/** The detail pane's tabs, in display order. */
export type DetailTab = 'documents' | 'links' | 'bom' | 'workflow' | 'changelog' | 'dfm' | 'tool' | 'equipment';

export const ARTICLE_DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: 'documents', label: 'Documents' },
  { key: 'links', label: 'Links' },
  { key: 'bom', label: 'BOM' },
  { key: 'workflow', label: 'Workflow' },
  { key: 'changelog', label: 'Changelog' },
];

export const TOOL_DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: 'dfm', label: 'DFM' },
  { key: 'tool', label: 'Tool' },
  { key: 'links', label: 'Links' },
  { key: 'changelog', label: 'Changelog' },
];

/** Gauges, assembly equipment and EOATs: their card first, then what every item has. */
export const EQUIPMENT_DETAIL_TABS: { key: DetailTab; label: string }[] = [
  { key: 'equipment', label: 'Equipment' },
  ...ARTICLE_DETAIL_TABS,
];

export function isEquipmentCategory(itemCategory: string): boolean {
  return itemCategory === 'gauge' || itemCategory === 'assembly_equipment';
}

/** Kept for anything still importing the plain article tab list. */
export const DETAIL_TABS = ARTICLE_DETAIL_TABS;

/** The tabs to show for a given item category, article tabs by default. */
export function detailTabsFor(itemCategory: string): { key: DetailTab; label: string }[] {
  if (isEquipmentCategory(itemCategory)) return EQUIPMENT_DETAIL_TABS;
  return itemCategory === 'tool' ? TOOL_DETAIL_TABS : ARTICLE_DETAIL_TABS;
}

/**
 * The tab to actually render: the remembered tab when it is valid for this
 * item's category, else that category's default (first) tab. This is how a
 * tool selection lands on DFM and an article selection lands back on
 * Documents, without ever overwriting the remembered tab in the parent.
 */
export function effectiveDetailTab(tab: DetailTab, itemCategory: string): DetailTab {
  const tabs = detailTabsFor(itemCategory);
  return tabs.some((t) => t.key === tab) ? tab : tabs[0].key;
}
