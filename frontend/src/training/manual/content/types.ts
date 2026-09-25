//: The ECR training content as data (draft, 2026-09-25).
//:
//: Written before the UI polish, so it is plain data instead of JSX: a block
//: list per section, rendered by render.tsx onto the kit in ../kit.tsx. When
//: the screens are final the copy is re-checked against the source (see
//: WIRING.md, "Labels to re-check") and the screenshot slots are filled.
//:
//: Section ids reuse the stub ids in ../chapters.tsx where one exists, so
//: wiring is "replace the stub body with renderBlocks(section.blocks)". New
//: sections carry ids prefixed with their chapter id, unique across the
//: manual, like the rest of the manual's anchors.
//:
//: House rules for the copy (asserted in content.test.ts): plain English,
//: short sentences, no em-dashes, no "TBD" or "TODO", every UI label written
//: exactly as the screen shows it, in double quotes.

/** A screenshot still to be taken. `shot` is the file stem in public/manual/. */
export interface ShotSlot {
  shot: string
  /** What the picture must show. Written for whoever takes the screenshot. */
  alt: string
  caption?: string
}

export type Block =
  | { lede: string }
  | { p: string }
  | { h3: string }
  /** Bulleted list; each item leads with a bold phrase. */
  | { points: [string, string][] }
  | { steps: { title: string; body: string }[] }
  | { callout: string; title?: string; tone?: 'note' | 'warn' | 'rule' }
  /** A two-column table: left is the thing, right is what it means. */
  | { table: { head: [string, string]; rows: [string, string][] } }
  | ShotSlot

export interface ContentSection {
  id: string
  title: string
  blocks: Block[]
}

export interface ContentChapter {
  /** Same id as the chapter in ../chapters.tsx. */
  id: string
  number: string
  title: string
  summary: string
  /** Training role keys (backend app/services/training.py CURRICULA). */
  roles?: TrainingRole[]
  sections: ContentSection[]
}

export type TrainingRole =
  | 'project_management'
  | 'sales'
  | 'engineering'
  | 'scheduling'
  | 'quality'
  | 'finance'

/**
 * Which real screen a practice task needs mounted in the sandbox.
 * The first three exist in ../../tasks.ts today. The rest are proposals:
 * each one needs a TaskScreen branch and sandbox handlers (WIRING.md).
 */
export type ScreenSpec =
  | { kind: 'start-change' }
  | { kind: 'change-status'; change: string }
  | { kind: 'assessment'; department: string }
  | { kind: 'scoping'; change: string }
  | { kind: 'costing'; change: string; department: string }
  | { kind: 'offer'; change: string }
  | { kind: 'timing'; change: string }
  | { kind: 'release'; change: string }
  | { kind: 'validation-issue'; change: string }
  | { kind: 'cost-sheet' }
  | { kind: 'intake' }

/**
 * A practice task, specified. Same fields as TrainingTask in ../../tasks.ts
 * (key, title, brief, why, screen) plus what the check must assert and what
 * the fixture must hold, so the check function can be written from it.
 */
export interface PracticeTaskSpec {
  /** The contract key. New keys go into backend CURRICULA and both tests. */
  key: string
  role: TrainingRole
  title: string
  /** What to do, in working language. Not how. */
  brief: string
  /** Why this task is in the check. Read once before starting. */
  why: string
  screen: ScreenSpec
  /** What the training copy must hold before the trainee starts. */
  fixture: string[]
  /**
   * Pass criteria, in order. Each is one assertion on the outcome (what the
   * record says afterwards), never on which buttons were pressed. The hint is
   * what the trainee reads when that assertion fails.
   */
  pass: { assert: string; hint: string }[]
  /**
   * 'ready': runs on today's sandbox (screen and handlers exist, the key is
   * already in tasks.ts or can be added with a check only).
   * 'needs-sandbox': needs a new screen and handlers first.
   */
  status: 'ready' | 'needs-sandbox'
  /** The existing key in tasks.ts this spec replaces or keeps, if any. */
  replaces?: string
}
