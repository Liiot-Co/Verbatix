-- Fuentes explícitas para propuestas. Las asignaciones legadas no calibradas
-- se conservan, pero dejan de estar activas si el grupo nunca fue resuelto por
-- una persona.

alter table verbatim_codes drop constraint if exists verbatim_codes_source_check;
alter table verbatim_codes add constraint verbatim_codes_source_check
  check (source in (
    'engine_exact','engine_fuzzy','llm_classified','llm_suggestion',
    'semantic_cache','rule_brand_in_reason','homologation','analyst_manual',
    'audit_correction'
  ));

update verbatim_codes vc
   set is_active = false
  from verbatims v
  join mention_groups mg on mg.id = v.mention_group_id
 where vc.verbatim_id = v.id
   and vc.is_active
   and mg.status <> 'resolved'
   and vc.source in ('engine_fuzzy','llm_classified','semantic_cache');

update mention_groups mg
   set status = case when suggested_code_id is null then 'pending_review' else 'suggested' end
 where mg.status = 'auto_coded'
   and not exists (
     select 1 from verbatims v
     join verbatim_codes vc on vc.verbatim_id = v.id and vc.is_active
     where v.mention_group_id = mg.id
   );

update verbatims v
   set coding_status = case
     when mg.suggested_code_id is null then 'pending' else 'suggested'
   end
  from mention_groups mg
 where mg.id = v.mention_group_id
   and mg.status in ('pending_review','suggested')
   and v.coding_status = 'auto_coded'
   and not exists (
     select 1 from verbatim_codes vc
      where vc.verbatim_id = v.id and vc.is_active
   );
