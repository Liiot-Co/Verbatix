-- Rename remaining legacy column names to match table renames from 011.
-- estudios.proyecto_id  -> studies.project_id  (FK to projects table)
-- rounds.project_id     -> rounds.study_id     (FK to studies table -> constrain later)
-- categories.project_id -> categories.study_id
-- questions.project_id  -> questions.study_id
-- codebooks.project_id  -> codebooks.study_id
-- assignments.project_id -> assignments.study_id

-- Step 1: rename the table (studios -> studies)
alter table if exists studios rename to studies;

-- Step 2: rename FK columns on studies itself
alter table studies rename column proyecto_id to project_id;

-- Step 3: rename FK columns on tables that reference studies
alter table rounds      rename column project_id to study_id;
alter table categories  rename column project_id to study_id;
alter table questions   rename column project_id to study_id;
alter table codebooks   rename column project_id to study_id;
alter table assignments rename column project_id to study_id;

-- Step 4: update FK constraint names (Postgres auto-generates them)
-- We drop the old-named constraints and re-add with new names.

-- studies.project_id -> projects.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'studies' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%proyecto%';
  if fk_name is not null then
    execute format('alter table studies drop constraint %I', fk_name);
  end if;
end $$;
alter table studies add constraint studies_project_id_fkey
  foreign key (project_id) references projects(id);

-- rounds.study_id -> studies.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'rounds' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%project%' and constraint_name not like '%category%';
  if fk_name is not null then
    execute format('alter table rounds drop constraint %I', fk_name);
  end if;
end $$;
alter table rounds add constraint rounds_study_id_fkey
  foreign key (study_id) references studies(id);

-- categories.study_id -> studies.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'categories' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%project%';
  if fk_name is not null then
    execute format('alter table categories drop constraint %I', fk_name);
  end if;
end $$;
alter table categories add constraint categories_study_id_fkey
  foreign key (study_id) references studies(id);

-- questions.study_id -> studies.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'questions' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%project%';
  if fk_name is not null then
    execute format('alter table questions drop constraint %I', fk_name);
  end if;
end $$;
alter table questions add constraint questions_study_id_fkey
  foreign key (study_id) references studies(id);

-- codebooks.study_id -> studies.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'codebooks' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%project%';
  if fk_name is not null then
    execute format('alter table codebooks drop constraint %I', fk_name);
  end if;
end $$;
alter table codebooks add constraint codebooks_study_id_fkey
  foreign key (study_id) references studies(id);

-- assignments.study_id -> studies.id
do $$
declare
  fk_name text;
begin
  select constraint_name into fk_name
    from information_schema.table_constraints
   where table_name = 'assignments' and constraint_type = 'FOREIGN KEY'
     and constraint_name like '%project%';
  if fk_name is not null then
    execute format('alter table assignments drop constraint %I', fk_name);
  end if;
end $$;
alter table assignments add constraint assignments_study_id_fkey
  foreign key (study_id) references studies(id);

-- Step 5: update unique constraint names (the names reference old column names)
-- We drop + recreate so ORM constraint names match.

alter table questions   drop constraint if exists questions_project_id_question_key_key;
alter table questions   add constraint questions_study_id_question_key_key
  unique (study_id, question_key);

alter table rounds      drop constraint if exists rounds_project_id_round_number_key;
alter table rounds      add constraint rounds_study_id_round_number_key
  unique (study_id, round_number);

alter table codebooks   drop constraint if exists codebooks_project_id_coding_type_version_key;
alter table codebooks   add constraint codebooks_study_id_coding_type_version_key
  unique (study_id, coding_type, version);

alter table assignments drop constraint if exists assignments_project_id_user_id_key;
alter table assignments add constraint assignments_study_id_user_id_key
  unique (study_id, user_id);

-- Step 6: update index names
do $$
declare
  idx_name text;
begin
  for idx_name in
    select indexname from pg_indexes
    where tablename = 'categories' and indexname like '%project%'
  loop
    execute format('alter index %I rename to categories_study_id_idx', idx_name);
  end loop;
  for idx_name in
    select indexname from pg_indexes
    where tablename = 'rounds' and indexname like '%project%'
  loop
    execute format('alter index %I rename to rounds_study_id_idx', idx_name);
  end loop;
  for idx_name in
    select indexname from pg_indexes
    where tablename = 'questions' and indexname like '%project%'
  loop
    execute format('alter index %I rename to questions_study_id_idx', idx_name);
  end loop;
end $$;

-- Step 7: update trigger (if any)
drop trigger if exists t_proyectos on projects;
create trigger t_proyectos before update on projects for each row execute function touch_updated_at();
