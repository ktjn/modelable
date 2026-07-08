from __future__ import annotations

import hashlib

from modelable.compiler.workspace import load_workspace
from modelable.emitters.sql import emit_sql


def test_emit_sql_postgres_basic(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain alerts {
  owner: "test-team"
  entity AlertRule @ 1 (additive) {
    @key ruleId: uuid
    name: string
    threshold: float
    enabled: bool
    createdAt?: timestamp
  }

  projection AlertRuleRow @ 1
    from alerts.AlertRule @ 1 as a
  {
    ruleId <- a.ruleId
    name <- a.name
    threshold <- a.threshold
    enabled <- a.enabled
    createdAt <- a.createdAt
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "alerts.AlertRuleRow@1")
    assert "CREATE TABLE IF NOT EXISTS alert_rule_row" in art.content
    assert "rule_id UUID NOT NULL" in art.content
    assert "name TEXT NOT NULL" in art.content
    assert "threshold DOUBLE PRECISION NOT NULL" in art.content
    assert "enabled BOOLEAN NOT NULL" in art.content
    assert "created_at TIMESTAMPTZ" in art.content
    # optional field should NOT have NOT NULL
    assert "created_at TIMESTAMPTZ NOT NULL" not in art.content
    assert art.content_hash == hashlib.sha256(art.content.encode("utf-8")).hexdigest()


def test_emit_sql_postgres_table_name_from_binding(tmp_path):
    (tmp_path / "all.mdl").write_text(
        """
domain orders {
  owner: "test-team"
  entity Order @ 1 (additive) {
    @key orderId: uuid
    total: int
  }

  projection OrderRow @ 1
    from orders.Order @ 1 as o
  {
    orderId <- o.orderId
    total <- o.total
  }
}

binding pg-conn {
  adapter: postgres
}

binding order-binding {
  model: orders.Order @ 1
  adapter: pg-conn
  table: "orders"
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "orders.OrderRow@1")
    assert "CREATE TABLE IF NOT EXISTS orders" in art.content
    assert "order_id UUID NOT NULL" in art.content
    assert "total BIGINT NOT NULL" in art.content


def test_emit_sql_postgres_wire_u64_maps_to_bigint(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain tracing {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    @wire(json: "string", rust.type: "u64")
    startTimeUnixNano: int
  }

  projection SpanRow @ 1
    from tracing.Span @ 1 as s
  {
    spanId <- s.spanId
    startTimeUnixNano <- s.startTimeUnixNano
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "tracing.SpanRow@1")
    assert "start_time_unix_nano BIGINT NOT NULL" in art.content


def test_emit_sql_postgres_decimal_type(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain finance {
  owner: "test-team"
  entity Invoice @ 1 (additive) {
    @key invoiceId: uuid
    amount: decimal(12, 2)
  }

  projection InvoiceRow @ 1
    from finance.Invoice @ 1 as i
  {
    invoiceId <- i.invoiceId
    amount <- i.amount
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "finance.InvoiceRow@1")
    assert "amount NUMERIC(12, 2) NOT NULL" in art.content


def test_emit_sql_postgres_fixed_width_integers(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain types {
  owner: "test-team"
  entity Widths @ 1 (additive) {
    @key id: uuid
    a: u8
    b: u16
    c: u32
    d: u64
    e: u128
    f: i8
    g: i16
    h: i32
    i: i64
    j: i128
  }

  projection WidthsRow @ 1
    from types.Widths @ 1 as w
  {
    id <- w.id
    a <- w.a
    b <- w.b
    c <- w.c
    d <- w.d
    e <- w.e
    f <- w.f
    g <- w.g
    h <- w.h
    i <- w.i
    j <- w.j
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "types.WidthsRow@1")
    assert "a SMALLINT NOT NULL" in art.content
    assert "b INTEGER NOT NULL" in art.content
    assert "c BIGINT NOT NULL" in art.content
    assert "d NUMERIC(20, 0) NOT NULL" in art.content
    assert "e NUMERIC(39, 0) NOT NULL" in art.content
    assert "f SMALLINT NOT NULL" in art.content
    assert "g SMALLINT NOT NULL" in art.content
    assert "h INTEGER NOT NULL" in art.content
    assert "i BIGINT NOT NULL" in art.content
    assert "j NUMERIC(39, 0) NOT NULL" in art.content
    assert "CHECK (a >= 0)" in art.content
    assert "CHECK (b >= 0)" in art.content
    assert "CHECK (c >= 0)" in art.content
    assert "CHECK (d >= 0)" in art.content
    assert "CHECK (e >= 0)" in art.content
    assert "CHECK (f >= 0)" not in art.content
    assert "CHECK (g >= 0)" not in art.content
    assert "CHECK (h >= 0)" not in art.content
    assert "CHECK (i >= 0)" not in art.content
    assert "CHECK (j >= 0)" not in art.content


def test_emit_sql_clickhouse_fixed_width_integers(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain types {
  owner: "test-team"
  entity Widths @ 1 (additive) {
    @key id: uuid
    a: u8
    b: u16
    c: u32
    d: u64
    e: u128
    f: i8
    g: i16
    h: i32
    i: i64
    j: i128
  }

  projection WidthsRow @ 1
    from types.Widths @ 1 as w
  {
    id <- w.id
    a <- w.a
    b <- w.b
    c <- w.c
    d <- w.d
    e <- w.e
    f <- w.f
    g <- w.g
    h <- w.h
    i <- w.i
    j <- w.j
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "clickhouse")
    art = next(a for a in artifacts if a.ref == "types.WidthsRow@1")
    assert "a UInt8" in art.content
    assert "b UInt16" in art.content
    assert "c UInt32" in art.content
    assert "d UInt64" in art.content
    assert "e UInt128" in art.content
    assert "f Int8" in art.content
    assert "g Int16" in art.content
    assert "h Int32" in art.content
    assert "i Int64" in art.content
    assert "j Int128" in art.content
    assert art.warnings == []


def test_emit_sql_clickhouse_basic(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain telemetry {
  owner: "test-team"
  entity Span @ 1 (additive) {
    @key spanId: string
    tenantId: uuid
    @wire(json: "string", rust.type: "u64")
    startTimeUnixNano: int
    name: string
    duration?: float
  }

  projection SpanRow @ 1
    from telemetry.Span @ 1 as s
  {
    spanId <- s.spanId
    @wire(clickhouse: "uuid")
    tenantId <- s.tenantId
    startTimeUnixNano <- s.startTimeUnixNano
    name <- s.name
    duration <- s.duration
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "clickhouse")
    art = next(a for a in artifacts if a.ref == "telemetry.SpanRow@1")
    assert "CREATE TABLE IF NOT EXISTS span_row" in art.content
    assert "ENGINE = MergeTree()" in art.content
    assert "ORDER BY tuple()" in art.content
    # uuid clickhouse wire hint
    assert "tenant_id UUID" in art.content
    # u64 rust hint maps to UInt64
    assert "start_time_unix_nano UInt64" in art.content
    # required string
    assert "name String" in art.content
    # optional float becomes Nullable
    assert "duration Nullable(Float64)" in art.content
    # @generated header
    assert "-- @generated by Modelable" in art.content


def test_emit_sql_clickhouse_table_name_from_binding(tmp_path):
    (tmp_path / "all.mdl").write_text(
        """
domain logs {
  owner: "test-team"
  entity Log @ 1 (additive) {
    @key logId: uuid
    message: string
  }

  projection LogRow @ 1
    from logs.Log @ 1 as l
  {
    logId <- l.logId
    message <- l.message
  }
}

binding ch-conn {
  adapter: clickhouse
}

binding log-binding {
  model: logs.Log @ 1
  adapter: ch-conn
  table: "logs"
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "clickhouse")
    art = next(a for a in artifacts if a.ref == "logs.LogRow@1")
    assert "CREATE TABLE IF NOT EXISTS logs" in art.content


def test_emit_sql_clickhouse_array_and_map_types(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain events {
  owner: "test-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    tags: array<string>
    attributes: map<string, string>
  }

  projection EventRow @ 1
    from events.Event @ 1 as e
  {
    eventId <- e.eventId
    tags <- e.tags
    attributes <- e.attributes
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "clickhouse")
    art = next(a for a in artifacts if a.ref == "events.EventRow@1")
    assert "Array(String)" in art.content
    assert "Map(String, String)" in art.content


def test_emit_sql_postgres_array_and_jsonb(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain events {
  owner: "test-team"
  entity Event @ 1 (additive) {
    @key eventId: uuid
    tags: array<string>
    metadata: map<string, int>
  }

  projection EventRow @ 1
    from events.Event @ 1 as e
  {
    eventId <- e.eventId
    tags <- e.tags
    metadata <- e.metadata
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "events.EventRow@1")
    assert "tags TEXT[] NOT NULL" in art.content
    assert "metadata JSONB NOT NULL" in art.content


def test_emit_sql_no_artifacts_for_models_only(tmp_path):
    """emit_sql only emits DDL for projections, not standalone models."""
    (tmp_path / "model.mdl").write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    assert artifacts == []


def test_emit_sql_artifact_path_is_flat(tmp_path):
    (tmp_path / "model.mdl").write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    name <- c.name
  }
}
""",
        encoding="utf-8",
    )
    workspace = load_workspace(tmp_path)
    artifacts = emit_sql(workspace, tmp_path / "out", "postgres")
    art = next(a for a in artifacts if a.ref == "customer.CustomerView@1")
    assert art.path.name == "customer.CustomerView.v1.sql"
