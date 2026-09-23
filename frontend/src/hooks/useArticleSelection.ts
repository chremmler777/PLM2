/**
 * Which item, revision and document the project detail shows.
 *
 * Shared by the project page and the pop-out detail window so both apply the
 * same revision rules: an explicit pick wins, otherwise the active revision,
 * otherwise the latest one.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { usePartRevisions } from './queries/useProjectDetail';
import type { Part, PartRevision } from '../components/project/projectTypes';

export interface ArticleSelection {
  partId: number | null;
  revisionId: number | null;
  viewingFileId: number | null;
  openDocId: number | null;
  partRevisions: PartRevision[] | undefined;
  /** Select an item. The document view resets when the item actually changes. */
  selectPart(partId: number | null): void;
  /** Select an item and reset the document view right away. */
  openPart(partId: number | null): void;
  /** Select a revision of the current item and reset the document view. */
  selectRevision(revisionId: number): void;
  /** Jump to a given revision of a given item (tree revision chips, pop-out sync). */
  pickRevision(partId: number, revisionId: number): void;
  setRevisionId(revisionId: number | null): void;
  setViewingFileId(fileId: number | null): void;
  setOpenDocId(fileId: number | null): void;
}

/**
 * The selected revision when it belongs to the selected part's loaded
 * revisions, else null. Right after an item switch revisionId still holds the
 * previous item's revision until the new list loads; this never pairs them.
 */
export function revisionOfSelectedPart(
  sel: Pick<ArticleSelection, 'revisionId' | 'partRevisions'>,
): number | null {
  if (sel.revisionId === null) return null;
  return sel.partRevisions?.some((r) => r.id === sel.revisionId) ? sel.revisionId : null;
}

export function useArticleSelection(parts: Part[] | undefined, initialPartId: number | null = null): ArticleSelection {
  const [partId, setPartId] = useState<number | null>(initialPartId);
  const [revisionId, setRevisionId] = useState<number | null>(null);
  const [viewingFileId, setViewingFileId] = useState<number | null>(null);
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  const { data: partRevisions } = usePartRevisions(partId || 0);

  // An explicit revision pick (a revision chip in the tree, a pop-out sync)
  // wins over the default selection below, which otherwise resets to the
  // active or latest revision whenever partId changes.
  const pendingRevisionRef = useRef<{ partId: number; revisionId: number } | null>(null);

  useEffect(() => {
    setViewingFileId(null);
    setOpenDocId(null);
    // A pending pick only guards the part change it was made for. Once partId
    // has moved on, drop it, or a later re-select of the original part (with
    // revisions already cached) would wrongly reapply the stale pick.
    if (pendingRevisionRef.current && pendingRevisionRef.current.partId !== partId) {
      pendingRevisionRef.current = null;
    }
    if (pendingRevisionRef.current?.partId === partId) {
      const pending = pendingRevisionRef.current;
      if (partRevisions?.some((r) => r.id === pending.revisionId)) {
        pendingRevisionRef.current = null;
        setRevisionId(pending.revisionId);
        return;
      }
      if (!partRevisions) {
        // Revisions for this part have not loaded yet: wait for the next run
        // instead of falling through to the default selection. A loaded but
        // empty list means the pick can never apply, so it is dropped below.
        return;
      }
      pendingRevisionRef.current = null;
    }
    if (!partRevisions || partRevisions.length === 0) {
      setRevisionId(null);
      return;
    }
    const activeId = parts?.find((p) => p.id === partId)?.active_revision_id;
    const fallback = partRevisions[partRevisions.length - 1].id;
    setRevisionId(partRevisions.some((r) => r.id === activeId) ? activeId! : fallback);
  }, [partId, partRevisions, parts]);

  const openPart = useCallback((id: number | null) => {
    setPartId(id);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  const selectRevision = useCallback((id: number) => {
    setRevisionId(id);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  const pickRevision = useCallback((pid: number, rid: number) => {
    pendingRevisionRef.current = { partId: pid, revisionId: rid };
    setPartId(pid);
    setRevisionId(rid);
    setViewingFileId(null);
    setOpenDocId(null);
  }, []);

  return {
    partId, revisionId, viewingFileId, openDocId, partRevisions,
    selectPart: setPartId, openPart, selectRevision, pickRevision,
    setRevisionId, setViewingFileId, setOpenDocId,
  };
}
