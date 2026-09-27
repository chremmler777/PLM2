import { engineeringChapter, engineeringTasks } from './engineering'
import { financeChapter, financeTasks } from './finance'
import { pmChapter, pmTasks } from './projectManagement'
import { qualityChapter, qualityTasks } from './quality'
import { salesChapter, salesTasks } from './sales'
import { schedulingChapter, schedulingTasks } from './scheduling'
import { basicsChapter, flowChapter } from './shared'
import type { ContentChapter, PracticeTaskSpec, ShotSlot, TrainingRole } from './types'

//: Entry point of the draft content. Nothing in the app imports it yet; see
//: WIRING.md for how it is plugged into ../chapters.tsx and ../../tasks.ts.
//: Chapter 09 (the training record) is already written in ../chapters.tsx and
//: is not repeated here.

export * from './types'
export { APP_ADDRESS } from './shared'

/** Chapters 01 to 08, in manual order. */
export const CONTENT_CHAPTERS: ContentChapter[] = [
  basicsChapter,
  flowChapter,
  pmChapter,
  salesChapter,
  engineeringChapter,
  schedulingChapter,
  qualityChapter,
  financeChapter,
]

export const PRACTICE_TASKS_BY_ROLE: Record<TrainingRole, PracticeTaskSpec[]> = {
  project_management: pmTasks,
  sales: salesTasks,
  engineering: engineeringTasks,
  scheduling: schedulingTasks,
  quality: qualityTasks,
  finance: financeTasks,
}

export const PRACTICE_TASKS: PracticeTaskSpec[] = Object.values(PRACTICE_TASKS_BY_ROLE).flat()

/** Every screenshot slot, in manual order: the shot list for after the polish. */
export const SHOT_SLOTS: (ShotSlot & { chapter: string; section: string })[] =
  CONTENT_CHAPTERS.flatMap((c) =>
    c.sections.flatMap((s) =>
      s.blocks
        .filter((b): b is ShotSlot => 'shot' in b)
        .map((b) => ({ ...b, chapter: c.id, section: s.id })),
    ),
  )

/** A chapter's content by its id (the ids of ../chapters.tsx). */
export function contentFor(chapterId: string): ContentChapter | undefined {
  return CONTENT_CHAPTERS.find((c) => c.id === chapterId)
}
