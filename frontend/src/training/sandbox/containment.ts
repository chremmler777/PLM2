/**
 * Training containment: the rule that nothing done in a training sandbox
 * reaches the live API. Ported from TWOS (frontend/src/training/sandbox/
 * adapter.ts there), split into its own module so the shared axios client can
 * import it without importing the whole sandbox.
 *
 * Swapping at the transport layer (the adapter on the shared client) is what
 * makes "training never touches the real database" a property of the
 * architecture rather than a filter forty call sites must remember. This file
 * is the part that makes a leak loud instead of invisible.
 */

//: Requests that deliberately go to the real server while a sandbox is open.
//: Neither carries an operational record:
//:
//:   /v1/auth/me     identity; the app cannot render without it, and it is the
//:                   one thing that must stay true rather than simulated.
//:   /v1/training/*  the training record itself. An attempt has to reach the
//:                   database or nothing was assessed.
//:
//: Nothing that mutates a change, and nothing user-specific beyond these, may
//: be added here. The rule is enforced by adapter.test.ts.
export const PASSTHROUGH: readonly string[] = ['/v1/auth/me']

const TRAINING_PREFIX = '/v1/training'

/** Marks the sandbox's own adapter so the client can tell it from the network. */
export const TRAINING_ADAPTER = Symbol.for('plm2.trainingAdapter')

//: How many sandboxes are currently installed. Zero in the live app.
let openSandboxes = 0

export function sandboxOpened(): void {
  openSandboxes += 1
}

export function sandboxClosed(): void {
  openSandboxes = Math.max(0, openSandboxes - 1)
}

export function sandboxIsOpen(): boolean {
  return openSandboxes > 0
}

export function stripQuery(url: string): string {
  const i = url.indexOf('?')
  return (i === -1 ? url : url.slice(0, i)).replace(/\/+$/, '') || '/'
}

export function isPassthrough(url: string): boolean {
  const path = stripQuery(url)
  //: With the slash, plus the bare path: a plain startsWith would also let
  //: `/v1/trainingish` through, which is exactly the hole an allowlist must
  //: not have.
  return (
    path === TRAINING_PREFIX ||
    path.startsWith(`${TRAINING_PREFIX}/`) ||
    PASSTHROUGH.includes(path)
  )
}

export function isTrainingAdapter(adapter: unknown): boolean {
  return (
    typeof adapter === 'function' &&
    (adapter as unknown as Record<symbol, unknown>)[TRAINING_ADAPTER] === true
  )
}

/**
 * Throws when a request is about to escape a live sandbox.
 *
 * On `client` (network = false) a request the training adapter is about to
 * answer is fine; anything else is a screen that mounted before the adapter
 * did, or a component using its own transport. On `networkClient`
 * (network = true) only the passthrough routes may leave.
 */
export function assertContained(url: string, adapter?: unknown, network = false): void {
  if (!sandboxIsOpen() || isPassthrough(url)) return
  if (!network && isTrainingAdapter(adapter)) return
  throw new Error(
    `Training containment: ${url} tried to reach the live system while a training ` +
      'exercise was open. Nothing was sent. This is a gap in the training copy, not ' +
      'something you did.',
  )
}
