import json
from pathlib import Path

import pytest

from modelable.compiler.workspace import (
    WorkspaceDocumentSource,
    discover_mdl_files,
    load_workspace,
    load_workspace_from_sources,
)


def _write_model(path: Path, domain: str, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""
domain {domain} {{
  owner: "test-team"
  entity {model} @ 1 (additive) {{
    @key id: uuid
  }}
}}
""",
        encoding="utf-8",
    )


def test_discover_mdl_files_returns_single_file(tmp_path):
    mdl = tmp_path / "customer.mdl"
    _write_model(mdl, "customer", "Customer")

    assert discover_mdl_files(mdl) == [mdl]


def test_discover_mdl_files_returns_directory_files_in_stable_order(tmp_path):
    second = tmp_path / "z-last.mdl"
    first = tmp_path / "nested" / "a-first.mdl"
    ignored = tmp_path / "notes.txt"
    _write_model(second, "orders", "Order")
    _write_model(first, "customer", "Customer")
    ignored.write_text("not modelable", encoding="utf-8")

    assert discover_mdl_files(tmp_path) == [first, second]


def test_load_workspace_parses_all_discovered_files(tmp_path):
    _write_model(tmp_path / "customer.mdl", "customer", "Customer")
    _write_model(tmp_path / "orders.mdl", "orders", "Order")

    workspace = load_workspace(tmp_path)

    assert [source.path.name for source in workspace.sources] == [
        "customer.mdl",
        "orders.mdl",
    ]
    assert [domain.name for domain in workspace.mdl.domains] == ["customer", "orders"]
    assert workspace.errors == []


def test_load_workspace_reads_fixed_sibling_facet_sidecar_in_canonical_order(tmp_path: Path) -> None:
    """Removing sidecar discovery must leave the workspace without these normalized facts."""
    _write_model(tmp_path / "orders.mdl", "orders", "Order")
    (tmp_path / "modelable.facets.json").write_text(
        json.dumps(
            {
                "$schema": "modelable.facets/v1",
                "schemas": [
                    {
                        "identity": "org.example/retention-class@1",
                        "value_schema": {"type": "string", "enum": ["regulated"]},
                        "allowed_subjects": ["field"],
                        "propagation": "project",
                    },
                    {
                        "identity": "org.example/confidentiality@1",
                        "value_schema": {"type": "string"},
                        "allowed_subjects": ["declaration"],
                        "propagation": "inherit",
                    },
                ],
                "facets": [
                    {
                        "identity": "org.example/retention-class@1",
                        "value": "regulated",
                        "subject": "field:orders.Order@1#id",
                        "propagation": "project",
                    },
                    {
                        "identity": "org.example/confidentiality@1",
                        "value": "restricted",
                        "subject": "declaration:orders.Order@1",
                        "propagation": "inherit",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert workspace.errors == []
    assert [facet.identity.canonical for facet in workspace.facets] == [
        "org.example/confidentiality@1",
        "org.example/retention-class@1",
    ]
    assert [facet.interpretation for facet in workspace.facets] == ["known", "known"]


def test_load_workspace_preserves_missing_sidecar_compatibility(tmp_path: Path) -> None:
    """Adding sidecar support must not make an ordinary workspace require one."""
    _write_model(tmp_path / "orders.mdl", "orders", "Order")

    workspace = load_workspace(tmp_path)

    assert workspace.errors == []
    assert workspace.facets == ()
    assert workspace.facet_registry is None


@pytest.mark.parametrize(
    ("sidecar_text", "expected_message"),
    [
        ("{not valid JSON", "invalid JSON"),
        (
            json.dumps(
                {
                    "$schema": "modelable.facets/v1",
                    "schemas": [
                        {
                            "identity": "org.example/retention-class@1",
                            "value_schema": {"type": "string"},
                            "allowed_subjects": ["field"],
                            "propagation": "none",
                        }
                    ],
                    "facets": [
                        {
                            "identity": "org.example/retention-class@1",
                            "value": 42,
                            "subject": "field:orders.Order@1#id",
                            "propagation": "none",
                        }
                    ],
                }
            ),
            "facet value",
        ),
    ],
)
def test_load_workspace_reports_invalid_facet_sidecars_as_diagnostics(
    tmp_path: Path, sidecar_text: str, expected_message: str
) -> None:
    """Swallowing malformed sidecars or known invalid values would hide semantic errors."""
    _write_model(tmp_path / "orders.mdl", "orders", "Order")
    (tmp_path / "modelable.facets.json").write_text(sidecar_text, encoding="utf-8")

    workspace = load_workspace(tmp_path)

    diagnostics = [diagnostic for diagnostic in workspace.errors if diagnostic.code == "FACET"]
    assert len(diagnostics) == 1
    assert expected_message in diagnostics[0].message
    assert diagnostics[0].path == str(tmp_path / "modelable.facets.json")


def test_load_workspace_from_sources_normalizes_explicit_in_memory_facet_document() -> None:
    """Removing the in-memory document argument would disconnect browser callers from facets."""
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="inmemory:///orders.mdl",
                text="""
domain orders {
  owner: \"test-team\"
  entity Order @ 1 (additive) {
    @key id: uuid
  }
}
""",
            )
        ],
        facets_document={
            "$schema": "modelable.facets/v1",
            "schemas": [],
            "facets": [
                {
                    "identity": "org.example/future-fact@1",
                    "value": True,
                    "subject": "field:orders.Order@1#id",
                    "propagation": "none",
                }
            ],
        },
    )

    assert workspace.errors == []
    assert workspace.facet_registry is not None
    assert [facet.as_dict() for facet in workspace.facets] == [
        {
            "identity": "org.example/future-fact@1",
            "value": True,
            "subject": "field:orders.Order@1#id",
            "propagation": "none",
            "interpretation": "unknown",
        }
    ]


def test_discover_mdl_files_rejects_path_without_mdl_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover_mdl_files(tmp_path)


def test_load_workspace_reports_duplicate_domains_across_files(tmp_path):
    _write_model(tmp_path / "customer-a.mdl", "customer", "Customer")
    _write_model(tmp_path / "customer-b.mdl", "customer", "CustomerProfile")

    workspace = load_workspace(tmp_path)

    assert any("duplicate domain 'customer'" in diagnostic.message for diagnostic in workspace.errors)


def test_load_workspace_reports_duplicate_model_versions_across_files(tmp_path):
    _write_model(tmp_path / "customer-v1-a.mdl", "customer", "Customer")
    _write_model(tmp_path / "customer-v1-b.mdl", "customer", "Customer")

    workspace = load_workspace(tmp_path)

    assert any("duplicate model version customer.Customer@1" in diagnostic.message for diagnostic in workspace.errors)


def test_load_workspace_reports_duplicates_across_uri_only_sources():
    source_text = """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key id: uuid
  }
}
"""
    workspace = load_workspace_from_sources(
        [
            WorkspaceDocumentSource(
                path=None,
                uri="inmemory:///customer-a.mdl",
                text=source_text,
            ),
            WorkspaceDocumentSource(
                path=None,
                uri="inmemory:///customer-b.mdl",
                text=source_text,
            ),
        ]
    )

    assert any(
        diagnostic.message == "duplicate domain 'customer' also defined in inmemory:///customer-a.mdl"
        for diagnostic in workspace.errors
    )
    assert any(
        diagnostic.message == ("duplicate model version customer.Customer@1 also defined in inmemory:///customer-a.mdl")
        for diagnostic in workspace.errors
    )


def test_load_workspace_reports_auto_projection_generated_name_conflict(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }

  auto projections Customer @ 1 {
    db
    request
    reply
    event
  }

  projection CustomerReply @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert any(
        "generated projection name customer.CustomerReply@1 conflicts" in diagnostic.message
        for diagnostic in workspace.errors
    )


def test_load_workspace_deduplicates_identical_bindings_across_files(tmp_path):
    (tmp_path / "customer.mdl").write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
  }
}

binding pg-conn {
  adapter: postgres
}

binding customer-pg {
  adapter: pg-conn
  model: customer.Customer @ 1
  table: "customers"
}
""",
        encoding="utf-8",
    )
    (tmp_path / "order.mdl").write_text(
        """
domain order {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
  }
}

binding pg-conn {
  adapter: postgres
}

binding order-pg {
  adapter: pg-conn
  model: order.Order @ 1
  table: "orders"
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    assert not workspace.errors
    # identical pg-conn bindings must be deduplicated to a single entry
    pg_conn_count = sum(1 for b in workspace.mdl.bindings if b.name == "pg-conn")
    assert pg_conn_count == 1


def test_load_workspace_errors_on_conflicting_binding_definitions(tmp_path):
    (tmp_path / "a.mdl").write_text(
        """
domain alpha {
  owner: "test-team"
  entity Alpha @ 1 (additive) {
    @key alphaId: uuid
  }
}

binding shared-conn {
  adapter: postgres
}
""",
        encoding="utf-8",
    )
    (tmp_path / "b.mdl").write_text(
        """
domain beta {
  owner: "test-team"
  entity Beta @ 1 (additive) {
    @key betaId: uuid
  }
}

binding shared-conn {
  adapter: clickhouse
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    # same binding name with different adapter is a conflict
    assert any("binding 'shared-conn'" in d.message for d in workspace.errors)


def test_load_workspace_warns_on_unbound_optional_model_in_postcard_domain(tmp_path):
    """Issue #439: a domain that binds some models to postcard but leaves a
    sibling model with optional fields unbound silently reintroduces #430
    for that model -- warn instead of staying silent."""
    (tmp_path / "orders.mdl").write_text(
        """
domain orders {
  owner: "test-team"
  entity Cart @ 1 (additive) {
    @key cartId: uuid
    coupon?: string
  }
  entity Wishlist @ 1 (additive) {
    @key wishlistId: uuid
    note?: string
  }
}

binding cart-codec {
  model: orders.Cart @ 1
  adapter: postcard
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert not workspace.errors
    postcard_warnings = [w for w in workspace.warnings if w.code == "POSTCARD"]
    assert len(postcard_warnings) == 1
    assert "orders.Wishlist" in postcard_warnings[0].message
    assert "orders.Cart" not in postcard_warnings[0].message


def test_load_workspace_no_postcard_warning_when_no_model_is_postcard_bound(tmp_path):
    """A domain with no postcard bindings at all is not opining on encoding --
    optional fields there are just ordinary JSON-shaped output."""
    (tmp_path / "orders.mdl").write_text(
        """
domain orders {
  owner: "test-team"
  entity Wishlist @ 1 (additive) {
    @key wishlistId: uuid
    note?: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert not [w for w in workspace.warnings if w.code == "POSTCARD"]


def test_load_workspace_no_postcard_warning_when_unbound_model_has_no_optional_fields(tmp_path):
    """A sibling model with no optional fields has nothing for postcard's
    skip_serializing_if gap to corrupt, so it should not be flagged."""
    (tmp_path / "orders.mdl").write_text(
        """
domain orders {
  owner: "test-team"
  entity Cart @ 1 (additive) {
    @key cartId: uuid
    coupon?: string
  }
  entity Wishlist @ 1 (additive) {
    @key wishlistId: uuid
    note: string
  }
}

binding cart-codec {
  model: orders.Cart @ 1
  adapter: postcard
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    assert not [w for w in workspace.warnings if w.code == "POSTCARD"]


def test_load_workspace_postcard_warning_resolves_indirect_connector_binding(tmp_path):
    """The postcard warning must resolve two-level bindings the same way the
    Rust emitter does (a model binding referencing a connector binding's
    adapter by name)."""
    (tmp_path / "orders.mdl").write_text(
        """
domain orders {
  owner: "test-team"
  entity Cart @ 1 (additive) {
    @key cartId: uuid
    coupon?: string
  }
  entity Wishlist @ 1 (additive) {
    @key wishlistId: uuid
    note?: string
  }
}

binding cart-codec-conn {
  adapter: postcard
}

binding cart-row {
  model: orders.Cart @ 1
  adapter: cart-codec-conn
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)

    postcard_warnings = [w for w in workspace.warnings if w.code == "POSTCARD"]
    assert len(postcard_warnings) == 1
    assert "orders.Wishlist" in postcard_warnings[0].message
