import { createContext, useContext } from 'react'

/**
 * True for anything rendered inside the training sandbox.
 *
 * Almost nothing should care: the point of swapping the transport layer is
 * that screens do not need to know. Treat any new use of this as a smell to
 * argue about, not a pattern to follow (same rule as TWOS).
 */
export const InTrainingSandbox = createContext(false)

export function useInTrainingSandbox(): boolean {
  return useContext(InTrainingSandbox)
}
