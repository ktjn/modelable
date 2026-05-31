from __future__ import annotations

from modelable.commands.codegen import register_codegen_commands
from modelable.commands.compile import register_compile_commands
from modelable.commands.create import register_create_commands
from modelable.commands.diff import register_diff_commands
from modelable.commands.graph import register_graph_commands
from modelable.commands.lsp import register_lsp_commands
from modelable.commands.llm import register_llm_commands
from modelable.commands.scenario import register_scenario_commands
from modelable.commands.workspace import register_workspace_commands
import click


@click.group()
def cli() -> None:
    """Modelable domain-owned data model compiler.

    MVP workflows cover validate, resolve, lineage, diff, compile, docs,
    inspect, codegen, lsp, scenario, and create helpers. Deferred command
    families such as Apicurio publish/pull, OpenMetadata export/publish,
    and ODCS export are documented in docs/cli-spec.md for later phases.
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
