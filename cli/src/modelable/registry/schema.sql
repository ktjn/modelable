create table domains (
  name text primary key,
  owner text,
  description text
);

create table models (
  domain_name text not null,
  name text not null,
  kind text not null,
  primary key (domain_name, name)
);

create table model_versions (
  domain_name text not null,
  model_name text not null,
  version integer not null,
  change_kind text not null,
  source_path text not null,
  primary key (domain_name, model_name, version)
);

create table fields (
  domain_name text not null,
  model_name text not null,
  model_version integer not null,
  field_name text not null,
  position integer not null,
  type_json text not null,
  optional integer not null,
  is_key integer not null,
  is_pii integer not null,
  classification text,
  primary key (domain_name, model_name, model_version, field_name)
);

create table projections (
  domain_name text not null,
  name text not null,
  primary key (domain_name, name)
);

create table projection_versions (
  domain_name text not null,
  projection_name text not null,
  version integer not null,
  source_model text not null,
  source_version_json text not null,
  source_alias text not null,
  primary key (domain_name, projection_name, version)
);

create table projection_sources (
  domain_name text not null,
  projection_name text not null,
  projection_version integer not null,
  source_kind text not null,
  source_model text not null,
  source_version_json text not null,
  source_alias text not null,
  join_on text
);

create table projection_fields (
  domain_name text not null,
  projection_name text not null,
  projection_version integer not null,
  field_name text not null,
  position integer not null,
  mapping_json text not null,
  is_pii integer not null,
  classification text,
  primary key (domain_name, projection_name, projection_version, field_name)
);

create table field_mappings (
  domain_name text not null,
  projection_name text not null,
  projection_version integer not null,
  target_field text not null,
  mapping_kind text not null,
  source_alias text,
  source_field text,
  expression text
);

create table lineage_edges (
  source_ref text not null,
  target_ref text not null,
  edge_kind text not null
);

create table adapter_bindings (
  name text primary key,
  model_ref text not null,
  adapter text not null,
  table_name text
);

create table compatibility_reports (
  domain_name text not null,
  model_name text not null,
  from_version integer not null,
  to_version integer not null,
  status text not null
);

create table access_policies (
  subject_ref text not null,
  action text not null,
  grantee text not null
);

create table por_log (
  model_ref text not null,
  issuer text not null,
  issued_at text not null,
  signature text
);

create table registry_ids (
  name text primary key,
  allocated_id integer unique not null,
  first_registered_at text
);
