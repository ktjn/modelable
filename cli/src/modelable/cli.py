from __future__ import annotations

import click

from modelable.commands.apicurio import register_apicurio_commands
from modelable.commands.codegen import register_codegen_commands
from modelable.commands.compile import register_compile_commands
from modelable.commands.create import register_create_commands
from modelable.commands.diff import register_diff_commands
from modelable.commands.graph import register_graph_commands
from modelable.commands.llm import register_llm_commands
from modelable.commands.lsp import register_lsp_commands
from modelable.commands.runtime import register_runtime_commands
from modelable.commands.scenario import register_scenario_commands
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
register_create_commands(cli)
register_diff_commands(cli)
register_graph_commands(cli)
register_lsp_commands(cli)
register_llm_commands(cli)
register_codegen_commands(cli)
register_scenario_commands(cli)
register_runtime_commands(cli)
register_apicurio_commands(cli)
