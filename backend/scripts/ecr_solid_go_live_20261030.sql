-- ECR-solid go-live data (Christoph 2026-10-26 .. 10-30), run once after
-- migrations 117a..153. Repeatable: every step checks what is already there.
--
-- 1. People: the department members who have not logged in to PLM2 yet get
--    the row their first AdminPanel login would create (hub-managed '!',
--    viewer; login syncs role + departments from the hub). Eric Dean left
--    10-29: not created. Adriana Capri: no KTX login, skipped.
-- 2. Full names for everyone on the list (login rows carry the username).
-- 3. Departments (membership as on AdminPanel; the login sync keeps it).
-- 4. Managers (escalation overview) and heads.
-- 5. Project teams 1302, 1383, 1432, 1748, 1864, 1994, 2277: the Atlas (1864)
--    team; 1748 PM = Steven (backup Cody). Quality backup = Udo (manager, holds the Quality role; Eric Dean left 10-29).
begin;

create temp table golive_people (un text primary key, full_name text, depts text[]) on commit drop;
insert into golive_people values
 ('cody.hrtyanski','Cody Hrtyanski','{Project Manager}'),
 ('steven.stocks','Steven Stocks','{Project Manager}'),
 ('carlos.gonzalez','Carlos Gonzalez','{Project Manager}'),
 ('george.richardson','George Richardson','{APQP}'),
 ('apurva.mhetre','Apurva Mhetre','{APQP}'),
 ('dale.perry','Dale Perry','{Tool Engineer}'),
 ('russ.addison','Russ Addison','{Manufacturing Engineer}'),
 ('cory.mccall','Cory McCall','{Manufacturing Engineer}'),
 ('christopher.holmes','Chris Holmes','{Process Engineer}'),
 ('nathan.payne','Nathan Payne','{Process Engineer}'),
 ('alexa.earls','Alexa Earls','{Logistics,Packaging Engineer}'),
 ('jessica.brown','Jessica Brown','{Logistics}'),
 ('christoph.demmler','Christoph Demmler','{Development,Manufacturing Engineer,Process Engineer,Tool Engineer}'),
 ('kenny.rice','Kenny Rice','{Packaging Engineer}'),
 ('karl.limburg','Karl Limburg','{Sales}'),
 ('roman.somin','Roman Somin','{Sales}'),
 ('jubei.hughes','Jubei Hughes','{Sales}'),
 ('udo.schwabe','Udo Schwabe','{APQP,Quality}'),
 ('sonja.bennett','Sonja Bennett','{Quality}'),
 ('kelly.carey','Kelly Carey','{Finance}'),
 ('sherry.garmon','Sherry Garmon','{Finance}'),
 ('brandon.belk','Brandon Belk','{Toolshop}'),
 ('mathew.chumley','Mathew Chumley','{Toolshop}'),
 ('carey.craft','Carey Craft','{Toolshop}'),
 ('tim.lawson','Tim Lawson','{Toolshop}'),
 ('huascar.miranda','Huascar Miranda','{Management}'),
 ('thomas.reinert','Thomas Reinert','{Management}');

-- 1. rows a first login would create
insert into users (organization_id, email, username, full_name, hashed_password, role,
                   is_active, created_at, mfa_enabled, data_clearance,
                   must_change_password, failed_login_attempts)
select (select min(id) from organizations), p.un, p.un, p.full_name, '!', 'viewer',
       true, now(), false, 'internal', false, 0
from golive_people p
where not exists (select 1 from users u where u.email = p.un or u.username = p.un);

-- 2. full names (only where the row still shows the bare username)
update users u set full_name = p.full_name
from golive_people p
where u.username = p.un and (u.full_name is null or u.full_name = '' or u.full_name = u.username);

-- 3. departments
insert into user_departments (user_id, department_id)
select u.id, d.id
from golive_people p
join users u on u.username = p.un
join wf_departments d on d.name = any (p.depts) and d.is_active
on conflict do nothing;

-- 4. managers and heads
update wf_departments d set manager_id = u.id
from (values ('Project Manager','steven.stocks'), ('APQP','udo.schwabe'), ('Quality','udo.schwabe'),
             ('Development','christoph.demmler'), ('Manufacturing Engineer','christoph.demmler'),
             ('Process Engineer','christoph.demmler'), ('Tool Engineer','christoph.demmler'),
             ('Logistics','alexa.earls'), ('Packaging Engineer','alexa.earls'),
             ('Finance','kelly.carey'), ('Toolshop','brandon.belk'),
             ('Management','thomas.reinert'), ('Sales','jubei.hughes')) m(dn, un)
join users u on u.username = m.un
where d.name = m.dn;

update wf_departments d set head_id = u.id
from (values ('Development','christoph.demmler'), ('Manufacturing Engineer','russ.addison'),
             ('Packaging Engineer','kenny.rice'), ('Process Engineer','christopher.holmes'),
             ('Tool Engineer','dale.perry')) h(dn, un)
join users u on u.username = h.un
where d.name = h.dn;

-- 5. project teams (one row per project + department; an existing row is left alone)
insert into project_responsibles (project_id, department_id, user_id, backup_user_id, set_by, set_at)
select pr.id, d.id, r.id, b.id, (select id from users where username = 'christoph.demmler'), now()
from projects pr
cross join (values
  ('Project Manager','cody.hrtyanski','steven.stocks'),
  ('APQP','apurva.mhetre','george.richardson'),
  ('Tool Engineer','dale.perry','christoph.demmler'),
  ('Manufacturing Engineer','russ.addison','cory.mccall'),
  ('Process Engineer','christopher.holmes','nathan.payne'),
  ('Logistics','alexa.earls','jessica.brown'),
  ('Development','christoph.demmler',null),
  ('Packaging Engineer','kenny.rice','alexa.earls'),
  ('Sales','karl.limburg','jubei.hughes'),
  ('Quality','sonja.bennett','udo.schwabe'),
  ('Finance','kelly.carey','sherry.garmon'),
  ('Toolshop','brandon.belk','carey.craft'),
  ('Management','thomas.reinert','huascar.miranda')) t(dn, resp, backup)
join wf_departments d on d.name = t.dn
join users r on r.username = t.resp
left join users b on b.username = t.backup
where pr.code in ('1302','1383','1432','1748','1864','1994','2277')
  and not exists (select 1 from project_responsibles x
                  where x.project_id = pr.id and x.department_id = d.id);

-- 1748: Steven is PM, Cody backup (Christoph 10-27)
update project_responsibles r
set user_id = s.id, backup_user_id = c.id
from projects pr, wf_departments d, users s, users c
where r.project_id = pr.id and pr.code = '1748'
  and r.department_id = d.id and d.name = 'Project Manager'
  and s.username = 'steven.stocks' and c.username = 'cody.hrtyanski';

-- Quality: Udo backs Sonja up where no backup is set (Christoph 10-30)
update project_responsibles r
set backup_user_id = u.id
from projects pr, wf_departments d, users u
where r.project_id = pr.id and pr.code in ('1302','1383','1432','1748','1864','1994','2277')
  and r.department_id = d.id and d.name = 'Quality'
  and u.username = 'udo.schwabe' and r.backup_user_id is null;

commit;

-- check
select d.name, m.username as manager, h.username as head,
       (select string_agg(u.username, ', ' order by u.username) from user_departments ud
        join users u on u.id = ud.user_id where ud.department_id = d.id) as members
from wf_departments d left join users m on m.id = d.manager_id left join users h on h.id = d.head_id
where d.is_active order by d.name;
select pr.code, count(*) from project_responsibles r join projects pr on pr.id = r.project_id
group by 1 order by 1;
