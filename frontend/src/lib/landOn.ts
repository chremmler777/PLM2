/**
 * After a tab switch, land on the section a button names: the Customer
 * answer panel sits a screen or more below the offer's own steps (audit
 * 2026-10-29 P3-5: "Record the customer answer" opened the Offer tab at the
 * top). The delay lets the tab render first.
 */
export const ANSWER_KINDS = new Set(['customer_response', 'answer'])

export function landOnCustomerAnswer(delayMs = 150): void {
  window.setTimeout(() => document.querySelector('[data-testid="customer-decision"]')
    ?.scrollIntoView?.({ behavior: 'smooth', block: 'start' }), delayMs)
}
