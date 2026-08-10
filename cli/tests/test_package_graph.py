import pytest

from modelable.emitters.package_graph import PackageGraph, build_package_graph
from modelable.parser.parse import parse_text_to_ir


def test_no_packages_returns_empty_graph():
    mdl = parse_text_to_ir(
        """
domain dom1 {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph == PackageGraph()


def test_single_package_no_deps():
    mdl = parse_text_to_ir(
        """
domain dom1 {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom1"]
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph.edges == {"pkg-a": set()}
    assert graph.package_for_domain == {"dom1": "pkg-a"}


def test_ref_type_creates_cross_package_dependency():
    mdl = parse_text_to_ir(
        """
domain dom_b {
  owner: "team"
  entity Other @ 1 (additive) {
    @key id: uuid
  }
}

domain dom_a {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
    other: ref<dom_b.Other@1>
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom_a"]
  }
  package "pkg-b" {
    include: ["dom_b"]
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph.edges["pkg-a"] == {"pkg-b"}
    assert graph.edges["pkg-b"] == set()


def test_named_semantic_type_creates_cross_package_dependency():
    mdl = parse_text_to_ir(
        """
domain dom_b {
  owner: "team"
  semantic Money: decimal(10, 2)
}

domain dom_a {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
    price: dom_b.Money
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom_a"]
  }
  package "pkg-b" {
    include: ["dom_b"]
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph.edges["pkg-a"] == {"pkg-b"}


def test_projection_join_creates_cross_package_dependency():
    mdl = parse_text_to_ir(
        """
domain dom_b {
  owner: "team"
  entity Other @ 1 (additive) {
    @key id: uuid
  }
}

domain dom_a {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
  }

  projection ThingView @ 1
    from dom_a.Thing @ 1 as t
    join dom_b.Other @ 1 as o on t.id == o.id
  {
    id <- t.id
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom_a"]
  }
  package "pkg-b" {
    include: ["dom_b"]
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph.edges["pkg-a"] == {"pkg-b"}


def test_direct_edges_are_not_transitively_expanded():
    mdl = parse_text_to_ir(
        """
domain dom_c {
  owner: "team"
  entity Leaf @ 1 (additive) {
    @key id: uuid
  }
}

domain dom_b {
  owner: "team"
  entity Other @ 1 (additive) {
    @key id: uuid
    leaf: ref<dom_c.Leaf@1>
  }
}

domain dom_a {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
    other: ref<dom_b.Other@1>
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom_a"]
  }
  package "pkg-b" {
    include: ["dom_b"]
  }
  package "pkg-c" {
    include: ["dom_c"]
  }
}
"""
    )
    graph = build_package_graph(mdl)
    assert graph.edges["pkg-a"] == {"pkg-b"}
    assert graph.edges["pkg-b"] == {"pkg-c"}
    assert graph.edges["pkg-c"] == set()


def test_cycle_detection_raises_value_error():
    mdl = parse_text_to_ir(
        """
domain dom_b {
  owner: "team"
  entity Other @ 1 (additive) {
    @key id: uuid
    thing: ref<dom_a.Thing@1>
  }
}

domain dom_a {
  owner: "team"
  entity Thing @ 1 (additive) {
    @key id: uuid
    other: ref<dom_b.Other@1>
  }
}

workspace "ws" {
  package "pkg-a" {
    include: ["dom_a"]
  }
  package "pkg-b" {
    include: ["dom_b"]
  }
}
"""
    )
    with pytest.raises(ValueError, match="cycle"):
        build_package_graph(mdl)
