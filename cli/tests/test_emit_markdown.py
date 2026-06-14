import hashlib

from click.testing import CliRunner

from modelable.cli import cli
from modelable.compiler.workspace import load_workspace
from modelable.emitters.markdown import emit_markdown


def test_emit_simple_model(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "customer-team"
  contact: "customer-team@example.com"
  description: "Customer identity and lifecycle."

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    legalName: string
    @pii
    email?: string
    marketingConsent: bool = false
    status: enum(active, blocked, deleted)
    createdAt: timestamp
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    assert len(artifacts) == 1

    art = artifacts[0]
    assert art.target == "markdown"
    assert art.ref == "customer.Customer@1"
    assert art.artifact_id == "customer.Customer.v1"
    assert isinstance(art.content, str)
    assert art.content_hash == hashlib.sha256(art.content.encode("utf-8")).hexdigest()

    text = art.content
    assert "# Customer v1" in text
    assert "**Domain:** customer" in text
    assert "**Name:** Customer" in text
    assert "**Artifact ID:** customer.Customer.v1" in text
    assert "**Artifact:** customer.Customer.v1.md" in text
    assert "**Owner:** customer-team" in text
    assert "**Contact:** customer-team@example.com" in text
    assert "**Description:** Customer identity and lifecycle." in text
    assert "**Kind:** entity" in text
    assert "**Change kind:** additive" in text
    assert "## Fields" in text
    assert "customerId" in text
    assert "uuid" in text
    assert "@key" in text
    assert "@pii" in text
    assert "marketingConsent" in text
    assert "false" in text
    assert "email" in text
    assert "no" in text  # optional field → Required: no
    assert "enum(active, blocked, deleted)" in text


def test_emit_model_field_types(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain test {
  owner: "test-team"
  entity Item @ 1 (additive) {
    @key id: uuid
    name: string
    count: int
    ratio: float
    price: decimal(10, 2)
    tags: array<string>
    meta: map<string, int>
    kind: enum(a, b, c)
    created: timestamp
    born: date
    slot: time
    ttl: duration
    blob: binary
    link: ref<other.Model>
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    assert len(artifacts) == 1
    text = artifacts[0].content
    assert "decimal(10,2)" in text
    assert "array<string>" in text
    assert "map<string,int>" in text
    assert "ref<other.Model>" in text
    assert "enum(a, b, c)" in text


def test_emit_projection_with_lineage(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain billing {
  owner: "billing-team"
  contact: "billing-team@example.com"
  description: "Billing projections over customer data."

  projection BillingCustomer @ 1
    from customer.Customer @ 2 as c
    where c.status == "active"
    group by c.status
  {
    billingId <- c.customerId
    name <- c.legalName
    @pii
    invoiceEmail <- c.email
    isActive = c.status == "active"
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    assert len(artifacts) == 1

    art = artifacts[0]
    assert art.ref == "billing.BillingCustomer@1"
    text = art.content

    assert "# BillingCustomer v1" in text
    assert "**Domain:** billing" in text
    assert "**Name:** BillingCustomer" in text
    assert "**Artifact ID:** billing.BillingCustomer.v1" in text
    assert "**Artifact:** billing.BillingCustomer.v1.md" in text
    assert "**Owner:** billing-team" in text
    assert "**Contact:** billing-team@example.com" in text
    assert "**Description:** Billing projections over customer data." in text
    assert "**Kind:** projection" in text
    assert "**Auto generated:** no" in text
    assert "**Source:** customer.Customer @ 2 as c" in text
    assert '**Where:** c.status == "active"' in text
    assert "**Group by:** c.status" in text
    assert "## Sources" in text
    assert "customer.Customer" in text
    assert "## Fields" in text
    assert "direct: c.customerId" in text
    assert "direct: c.legalName" in text
    assert "computed:" in text
    assert "@pii" in text


def test_emit_auto_projection(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    name: string
    @server
    internalId: string
  }

  auto projections Customer @ 1 {
    db
    request
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    refs = {a.ref for a in artifacts}
    assert "customer.CustomerDb@1" in refs
    assert "customer.CustomerRequest@1" in refs

    db_art = next(a for a in artifacts if a.ref == "customer.CustomerDb@1")
    assert "**Auto generated:** yes" in db_art.content

    # request projection should not include @server field
    req_art = next(a for a in artifacts if a.ref == "customer.CustomerRequest@1")
    assert "internalId" not in req_art.content


def test_emit_projection_version_str(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ >=1<3 as c
  {
    billingId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    text = artifacts[0].content
    assert ">=1<3" in text


def test_emit_projection_pinned_version_str(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain billing {
  owner: "test-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 2#a3f8b2c1d4e5f6a7 as c
  {
    billingId <- c.customerId
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    text = artifacts[0].content
    assert "2#a3f8b2c1d4e5f6a7" in text


def test_emit_classification_in_field_table(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
        """
domain customer {
  owner: "test-team"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    @classification("confidential")
    ssn: string
  }
}
""",
        encoding="utf-8",
    )

    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, tmp_path / "out")
    text = artifacts[0].content
    assert "confidential" in text


def test_emit_writes_files(tmp_path):
    mdl = tmp_path / "test.mdl"
    mdl.write_text(
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

    out = tmp_path / "out"
    out.mkdir()
    workspace = load_workspace(tmp_path)
    artifacts = emit_markdown(workspace, out)
    for art in artifacts:
        art.path.write_text(art.content, encoding="utf-8")

    assert (out / "customer.Customer.v1.md").exists()
    content = (out / "customer.Customer.v1.md").read_text(encoding="utf-8")
    assert "# Customer v1" in content


def test_cli_compile_markdown_writes_files(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
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

    out = tmp_path / "dist" / "docs"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(
            cli,
            ["compile", str(mdl), "--target", "markdown", "--out", str(out)],
        )

    assert result.exit_code == 0
    assert (out / "customer.Customer.v1.md").exists()
    assert any(
        len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split()
    )
    content = (out / "customer.Customer.v1.md").read_text(encoding="utf-8")
    assert "# Customer v1" in content


def test_cli_docs_command(tmp_path):
    mdl = tmp_path / "customer.mdl"
    mdl.write_text(
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

    out = tmp_path / "dist" / "docs"
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(cli, ["docs", str(mdl), "--out", str(out)])

    assert result.exit_code == 0
    assert (out / "customer.Customer.v1.md").exists()
    assert any(
        len(part) == 64 and all(ch in "0123456789abcdef" for ch in part.lower()) for part in result.output.split()
    )
