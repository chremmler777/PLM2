import { afterEach, describe, it, expect, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import WorkflowProgress from './WorkflowProgress'
import type { WfInstance, WfInstanceTask } from '../../types/workflow'

const task = (over: Partial<WfInstanceTask> = {}): WfInstanceTask => ({
  id: 5, instance_id: 1, stage_order: 1, step_id: 9, step_name: 'Design check',
  department_id: 2, department_name: 'Development', rasic_letter: 'R', status: 'active',
  is_actionable: true, completed_by: null, completed_at: null, decision: null, notes: null,
  owner_id: null, owner_name: null, accepted_at: null, due_date: null, overdue: false, ...over,
})
const instance = (over: Partial<WfInstance> = {}, t: WfInstanceTask = task()): WfInstance => ({
  id: 1, template_id: 3, template_name: 'ECN', part_revision_id: 7, status: 'active',
  current_stage_order: 1, started_by: 1, started_at: '2026-09-20T08:00:00', completed_at: null,
  canceled_at: null, cancel_reason: null, tasks: [t], ...over,
} as WfInstance)

const show = (i: WfInstance) => render(<WorkflowProgress instance={i} onCompleteTask={vi.fn()}
  onCancel={vi.fn()} isCompletingTask={false} isCanceling={false} />)

describe('WorkflowProgress approve and 3D evidence', () => {
  afterEach(cleanup)
  it('holds Approve on a CAD-evidence step while the revision has no 3D evidence, and says why', () => {
    show(instance({ has_3d_evidence: false }, task({ requires_cad_evidence: true })))
    const btn = screen.getByTestId('wf-approve-5') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(screen.getByTestId('wf-approve-why-5').textContent).toMatch(/3D evidence/)
    expect(btn.getAttribute('aria-describedby')).toBe('wf-approve-why-5')
  })

  it('lets Approve through once the evidence is there, or where the step does not need it', () => {
    show(instance({ has_3d_evidence: true }, task({ requires_cad_evidence: true })))
    expect((screen.getByTestId('wf-approve-5') as HTMLButtonElement).disabled).toBe(false)
    expect(screen.queryByTestId('wf-approve-why-5')).toBeNull()
  })

  it('does not hold a step that needs no evidence', () => {
    show(instance({ has_3d_evidence: null }, task({ requires_cad_evidence: false })))
    expect((screen.getByTestId('wf-approve-5') as HTMLButtonElement).disabled).toBe(false)
  })
})
