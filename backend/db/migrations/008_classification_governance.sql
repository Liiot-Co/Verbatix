-- =====================================================================
-- VERBATIX — gobernanza de clasificación de alta precisión
-- =====================================================================
-- Migración aditiva: reutiliza codebooks/codes/code_aliases,
-- reason_embeddings, processing_runs, mention_groups y audit_logs. No crea
-- tablas paralelas ni elimina histórico.

alter table codes
  add column if not exists definition text,
  add column if not exists inclusion_criteria jsonb not null default '[]'::jsonb,
  add column if not exists exclusion_criteria jsonb not null default '[]'::jsonb,
  add column if not exists examples jsonb not null default '[]'::jsonb,
  add column if not exists approval_status text not null default 'approved';

alter table codes drop constraint if exists codes_approval_status_check;
alter table codes add constraint codes_approval_status_check
  check (approval_status in ('pending', 'approved', 'revoked'));

-- El legado humano/importado/heredado sigue siendo utilizable. Lo generado por
-- motor queda como propuesta hasta una aprobación explícita.
update codes
   set approval_status = case when origin = 'engine_auto' then 'pending' else 'approved' end;

alter table code_aliases
  add column if not exists alias_kind text not null default 'positive',
  add column if not exists status text not null default 'approved',
  add column if not exists normalization_version text not null default 'canonical-v1',
  add column if not exists evidence jsonb not null default '{}'::jsonb,
  add column if not exists approved_at timestamptz,
  add column if not exists revoked_at timestamptz;

alter table code_aliases drop constraint if exists code_aliases_alias_kind_check;
alter table code_aliases add constraint code_aliases_alias_kind_check
  check (alias_kind in ('positive', 'negative', 'system'));
alter table code_aliases drop constraint if exists code_aliases_status_check;
alter table code_aliases add constraint code_aliases_status_check
  check (status in ('pending', 'approved', 'revoked', 'conflict'));

update code_aliases a
   set alias_kind = case when c.is_system then 'system' else 'positive' end,
       status = case
         when c.is_system then 'approved'
         when a.origin in ('engine_fuzzy', 'llm_promoted') then 'pending'
         else 'approved'
       end,
       approved_at = case
         when c.is_system or a.origin not in ('engine_fuzzy', 'llm_promoted')
           then coalesce(a.approved_at, a.created_at)
         else null
       end
  from codes c
 where c.id = a.code_id;

-- Si un legado contradice el principio alias->un código, se conserva pero se
-- marca como conflicto. No se elige un ganador por orden accidental.
with conflicting as (
  select codebook_id, alias_normalized
    from code_aliases
   where status = 'approved' and alias_kind in ('positive', 'system')
   group by codebook_id, alias_normalized
  having count(distinct code_id) > 1
)
update code_aliases a
   set status = 'conflict'
  from conflicting c
 where a.codebook_id = c.codebook_id
   and a.alias_normalized = c.alias_normalized
   and a.status = 'approved';

create unique index if not exists code_aliases_one_approved_target_uidx
  on code_aliases (codebook_id, alias_normalized)
  where status = 'approved' and alias_kind in ('positive', 'system');

alter table reason_embeddings
  add column if not exists approval_status text not null default 'pending',
  add column if not exists source text not null default 'legacy_llm';
alter table reason_embeddings drop constraint if exists reason_embeddings_approval_status_check;
alter table reason_embeddings add constraint reason_embeddings_approval_status_check
  check (approval_status in ('pending', 'approved', 'revoked'));

alter table processing_runs
  add column if not exists total_groups int not null default 0,
  add column if not exists policy_version text,
  add column if not exists prompt_version text,
  add column if not exists model_name text;

alter table mention_groups drop constraint if exists mention_groups_status_check;
alter table mention_groups add constraint mention_groups_status_check
  check (status in ('auto_coded', 'below_threshold', 'anomaly', 'pending_review',
                    'resolved', 'suggested', 'garbage', 'engine_error',
                    'abstained', 'conflict'));

alter table verbatims drop constraint if exists verbatims_coding_status_check;
alter table verbatims add constraint verbatims_coding_status_check
  check (coding_status in ('pending', 'auto_coded', 'needs_review',
                           'manually_coded', 'unknown', 'suggested',
                           'garbage', 'engine_error', 'abstained', 'conflict'));

alter table rounds drop constraint if exists rounds_status_check;
alter table rounds add constraint rounds_status_check
  check (status in ('created','files_uploaded','processing','codebook_review',
                    'preliminary_ready','manual_coding','audit_pending',
                    'audit_approved','nets_review','ready_to_export','completed','failed'));

alter table subprojects drop constraint if exists subprojects_status_check;
alter table subprojects add constraint subprojects_status_check
  check (status in ('created','files_uploaded','processing','codebook_review',
                    'preliminary_ready','manual_coding','audit_pending',
                    'audit_approved','nets_review','ready_to_export','completed','failed'));

-- Las asignaciones automáticas legadas hechas contra libros scratch que siguen
-- en draft no se borran: se desactivan y vuelven a revisión. Las reglas exactas
-- de sistema permanecen activas.
update verbatim_codes vc
   set is_active = false
  from verbatims v
  join subprojects sp on sp.id = v.subproject_id
  join codebooks cb on cb.id = sp.codebook_id
 where vc.verbatim_id = v.id
   and vc.is_active
   and cb.origin = 'scratch'
   and cb.status = 'draft'
   and vc.source in ('engine_fuzzy', 'engine_llm', 'semantic_cache');

update mention_groups mg
   set status = 'pending_review',
       created_by_run_id = null
  from subprojects sp
  join codebooks cb on cb.id = sp.codebook_id
 where mg.subproject_id = sp.id
   and cb.origin = 'scratch'
   and cb.status = 'draft'
   and mg.status = 'auto_coded'
   and not exists (
     select 1 from verbatims v
     join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
     where v.mention_group_id = mg.id
   );

update verbatims v
   set coding_status = 'pending'
  from subprojects sp
  join codebooks cb on cb.id = sp.codebook_id
 where v.subproject_id = sp.id
   and cb.origin = 'scratch'
   and cb.status = 'draft'
   and v.coding_status = 'auto_coded'
   and not exists (
     select 1 from verbatim_codes vc
      where vc.verbatim_id = v.id and vc.is_active
   );

update rounds r
   set status = 'codebook_review', updated_at = now()
 where exists (
   select 1 from subprojects sp
   join codebooks cb on cb.id = sp.codebook_id
   join verbatims v on v.subproject_id = sp.id
   where sp.round_id = r.id and cb.origin = 'scratch' and cb.status = 'draft'
 );

update subprojects sp
   set status = 'codebook_review', updated_at = now()
  from codebooks cb
 where cb.id = sp.codebook_id
   and cb.origin = 'scratch'
   and cb.status = 'draft'
   and exists (select 1 from verbatims v where v.subproject_id = sp.id);
