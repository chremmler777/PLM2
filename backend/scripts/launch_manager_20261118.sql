-- Launch Manager department + Todd Haynes on the project teams
-- (Christoph 2026-11-18: "launch manager same rights as apqp ... he has no
-- work in the ec for now so all viewer and active in LOP"; "teamsite needs
-- him added (he has no backup)").
--
-- Data only, repeatable, no migration (departments are data: Toolshop and
-- Management came the same way, scripts/ecr_solid_go_live_20261030.sql).
-- The code side is cost_sheet_service.NON_ROUTABLE_REASONS: "Launch Manager"
-- is never routed in a change and gets no cost-sheet rate, so run this only
-- on a database whose backend has that rule.
-- Members come from the AdminPanel role plm2_LaunchManager (hub_role).
--
--   docker exec -i compose-plm2-db-1 psql -U plm -d <db> -v ON_ERROR_STOP=1 < this file
begin;

-- 1. the department (action, like APQP; starts no change)
insert into wf_departments (name, flow_type, is_active, can_start_change,
                            can_start_internal_change, sort_order, created_at, hub_role)
select 'Launch Manager', 'action', true, false, false,
       (select coalesce(max(sort_order), 0) + 1 from wf_departments), now(),
       'plm2_LaunchManager'
where not exists (select 1 from wf_departments where name = 'Launch Manager');

update wf_departments set is_active = true, hub_role = 'plm2_LaunchManager'
where name = 'Launch Manager' and (not is_active or hub_role is distinct from 'plm2_LaunchManager');

-- 2. Todd is a member (the login sync keeps it once his AdminPanel role is in his token)
insert into user_departments (user_id, department_id)
select u.id, d.id from users u, wf_departments d
where u.username = 'todd.haynes' and d.name = 'Launch Manager'
  and not exists (select 1 from user_departments x
                  where x.user_id = u.id and x.department_id = d.id);

-- 3. project teams: Todd is the Launch Manager of every project that has a
--    team, no backup (an existing row is left alone)
insert into project_responsibles (project_id, department_id, user_id, backup_user_id, set_by, set_at)
select p.project_id, d.id, u.id, null, null, now()
from (select distinct project_id from project_responsibles) p,
     wf_departments d, users u
where d.name = 'Launch Manager' and u.username = 'todd.haynes'
  and not exists (select 1 from project_responsibles x
                  where x.project_id = p.project_id and x.department_id = d.id);

select d.id, d.name, d.is_active, d.hub_role, d.sort_order,
       (select count(*) from project_responsibles r where r.department_id = d.id) as team_rows,
       (select count(*) from user_departments m where m.department_id = d.id) as members
from wf_departments d where d.name = 'Launch Manager';

commit;
