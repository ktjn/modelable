from modelable.llm.render import render_mdl
from modelable.parser.parse import parse_text_to_ir


def test_render_mdl_preserves_editor_relevant_ir() -> None:
    source = """
domain customer {
  owner: "customer-team"
  contact: "customer@example.com"
  description: "Customer contracts"

  semantic CustomerId: uuid {
    registry: true
  }

  entity Customer @ 1 (additive) {
    reserved protobuf {
      numbers: [9]
      names: ["legacy_name"]
    }
    access {
      entity billing [read, project]
      property email support [read]
    }
    @key customerId: CustomerId
    @pii @classification("confidential") email?: string
    address: object { street: string city: string postalCode: string country: string }
  }

  index Customer @ 1 {
    primary customerId
    secondary byEmail {
      key: [email]
      sort: [customerId desc]
      unique: true
    }
  }
}

domain billing {
  owner: "billing-team"
  projection BillingCustomer @ 1
    from customer.Customer @ 1 as c
    left join customer.Customer @ 1 as parent on c.customerId == parent.customerId
      cardinality: many_to_one
    where c.email != ""
    group by c.customerId
  {
    reserved protobuf {
      numbers: [4]
      names: ["old_email"]
    }
    access {
      entity reporting [read]
    }
    customerId <- c.customerId
    emailCount = count(c.email)
  }
}

workspace default {
  name: "commerce"
  description: "Commerce contracts"
  ai {
    provider: "ollama"
    model: "llama3.1"
    repair_attempts: 2
  }
}
"""
    parsed = parse_text_to_ir(source)
    reparsed = parse_text_to_ir(render_mdl(parsed))

    assert reparsed == parsed


def test_render_mdl_preserves_pinned_sources_and_extended_types() -> None:
    source = """
domain metrics {
  owner: "metrics-team"
  entity Span @ 1 (additive) {
    @key spanId: uuid(7)
    @wire(json: "string", rust.type: "u64") count: u64
    digest: binary(32)
  }
  projection SpanView @ 1
    from metrics.Span @ 1#a3f8b2c1d4e5f6a7 as s
  {
    spanId <- s.spanId
  }
}
"""
    parsed = parse_text_to_ir(source)
    reparsed = parse_text_to_ir(render_mdl(parsed))

    assert reparsed == parsed
