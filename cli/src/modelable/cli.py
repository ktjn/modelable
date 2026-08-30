from __future__ import annotations

import click

from modelable.commands.apicurio import register_apicurio_commands
from modelable.commands.capabilities import register_capabilities_commands
from modelable.commands.codegen import register_codegen_commands
from modelable.commands.compile import register_compile_commands
from modelable.commands.config import register_config_commands
from modelable.commands.create import register_create_commands
from modelable.commands.diff import register_diff_commands
from modelable.commands.docs_ask import register_docs_ask_commands
from modelable.commands.docs_eval import register_docs_eval_commands
from modelable.commands.docs_index import register_docs_index_commands
from modelable.commands.doctor import register_doctor_commands
from modelable.commands.extract_enum import register_extract_enum_commands
from modelable.commands.graph import register_graph_commands
from modelable.commands.impact import register_impact_commands
from modelable.commands.llm import register_llm_commands
from modelable.commands.lsp import register_lsp_commands
from modelable.commands.plan import register_plan_commands
from modelable.commands.registry import register_registry_commands
from modelable.commands.runtime import register_runtime_commands
from modelable.commands.scenario import register_scenario_commands
from modelable.commands.spec import register_spec_commands
from modelable.commands.sync import register_sync_commands
from modelable.commands.transforms import register_transform_commands
from modelable.commands.validate_compat import register_validate_compat_commands
from modelable.commands.version_delta import register_version_delta_commands
from modelable.commands.workspace import register_workspace_commands


@click.group()
@click.version_option(package_name="modelable", prog_name="modelable")
def cli() -> None:
    """Modelable domain-owned data model compiler.

    MVP workflows cover validate, resolve, lineage, diff, compile, docs,
    inspect, codegen, lsp, scenario, create helpers, and Apicurio JSON Schema
    artifact publish/pull.
    """


register_workspace_commands(cli)
register_compile_commands(cli)
register_config_commands(cli)
register_create_commands(cli)
register_diff_commands(cli)
register_docs_index_commands(cli)
register_doctor_commands(cli)
register_docs_eval_commands(cli)
register_docs_ask_commands(cli)
register_extract_enum_commands(cli)
register_graph_commands(cli)
register_impact_commands(cli)
register_plan_commands(cli)
register_lsp_commands(cli)
register_llm_commands(cli)
register_codegen_commands(cli)
register_scenario_commands(cli)
register_runtime_commands(cli)
register_registry_commands(cli)
register_apicurio_commands(cli)
register_spec_commands(cli)
register_sync_commands(cli)
register_transform_commands(cli)
register_validate_compat_commands(cli)
register_capabilities_commands(cli)
register_version_delta_commands(cli)
