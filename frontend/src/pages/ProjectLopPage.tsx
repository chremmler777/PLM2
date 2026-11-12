/**
 * ProjectLopPage - one project's LOP (list of open points) on its own page,
 * full height, for the weekly meeting on a projector. The minutes mail and
 * the LOP notifications link here; the project page's LOP panel has an
 * "Open full page" link to it. The list itself is the same LopPanel; this
 * page only adds the heading (project number, then name) and the way back.
 */
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { getProjectLop, lopKeys } from '../api/lop'
import LopPanel from '../components/lop/LopPanel'
import { InlineError } from '../components/lop/lopUi'
import { lopErrorMessage } from '../components/lop/useLopWrite'
import { useProject } from '../hooks/queries/useProjectDetail'

function Heading({ code, name }: { code?: string | null; name?: string | null }) {
  return (
    <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
      {code ? <span className="tabular-nums">{code}</span> : 'Project'}
      {name && <span className="font-normal text-slate-300"> {name}</span>}
      <span className="ml-3 text-base font-normal text-slate-400">LOP</span>
    </h1>
  )
}

/** Without a LOP the LOP call says nothing about the project: name it from the project list. */
function NoLopHeading({ projectId }: { projectId: number }) {
  const project = useProject(projectId)
  return <Heading code={project.data?.code} name={project.data?.name} />
}

export default function ProjectLopPage() {
  const projectId = Number(useParams().projectId)
  // the same query LopPanel opens with (meeting view): one request, shared
  const lop = useQuery({
    queryKey: lopKeys.project(projectId, 'meeting'),
    queryFn: () => getProjectLop(projectId, 'meeting'),
    enabled: Number.isFinite(projectId),
  })
  const project = lop.data?.project

  return (
    <div className="flex min-h-full flex-col p-6">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        {lop.data === null ? <NoLopHeading projectId={projectId} /> : <Heading code={project?.code} name={project?.name} />}
        <Link to={`/projects/${projectId}`}
          className="inline-flex items-center gap-1.5 rounded text-sm text-sky-400 hover:text-sky-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-sky-400">
          <ArrowLeft aria-hidden="true" size={14} />Back to the project
        </Link>
      </div>

      {lop.isLoading ? (
        <p className="text-sm text-slate-400">Loading the LOP…</p>
      ) : lop.isError ? (
        <InlineError>{lopErrorMessage(lop.error, 'The LOP could not be loaded.')}</InlineError>
      ) : lop.data === null ? (
        <p className="text-sm text-slate-400">This project has no LOP.</p>
      ) : (
        <div className="flex-1 rounded-lg border border-slate-700 bg-slate-800 px-4 py-3">
          <LopPanel key={projectId} projectId={projectId} />
        </div>
      )}
    </div>
  )
}
