from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from modelable.cli import cli

SAMPLE_MDL = """
domain customer {
  owner: "customer-platform"
  contact: "customer-platform@example.com"
  description: "Customer identity sample for codegen smoke tests."

  entity Customer @ 1 (additive) {
    @key customerId: uuid
    displayName: string
    tags: array<string>
    nickname?: string
    metadata?: map<string, int>
    address?: object {
      line1: string
      line2?: string
    }
  }

  projection CustomerView @ 1
    from customer.Customer @ 1 as c
  {
    customerId <- c.customerId
    displayName <- c.displayName
    tags <- c.tags
    nickname <- c.nickname
    metadata <- c.metadata
    address <- c.address
  }
}
"""

PROTOBUF_SAMPLE_MDL = """
domain platform {
  owner: "platform-team"
  semantic SchemaId : u32 { registry: true }
}

domain customer {
  owner: "customer-platform"
  entity Customer @ 1 (additive) {
    @key customerId: uuid
    schemaId: SchemaId
  }
}
"""

SMOKE_UUID = "123e4567-e89b-12d3-a456-426614174000"

TARGETS = [
    ("csharp", "mcr.microsoft.com/dotnet/sdk:10.0", "dotnet"),
    ("java", "eclipse-temurin:25.0.3_9-jdk-ubi10-minimal", "javac"),
    ("python", "python:3.14.4-slim", "python"),
    ("rust", "rust:1.95.0", "cargo"),
    ("go", "golang:1.26.3", "go"),
    ("typescript", "node:26.0.0-slim", "npx"),
    ("protobuf", "python:3.14.4-slim", "protoc"),
]


def _docker_available() -> bool:
    result = subprocess.run(["docker", "version"], capture_output=True, text=True)
    return result.returncode == 0


def _run_docker(workdir: Path, image: str, command: str) -> subprocess.CompletedProcess[str]:
    mount = f"type=bind,source={workdir.resolve().as_posix()},target=/work"
    # Append a chmod step so root-owned build artifacts in /work become
    # world-accessible, allowing pytest to clean up tmp_path after the test.
    wrapped = f'{command}; _rc=$?; chmod -R a+rwX /work 2>/dev/null || true; exit "$_rc"'
    return subprocess.run(
        ["docker", "run", "--rm", "--mount", mount, "--workdir", "/work", image, "sh", "-lc", wrapped],
        capture_output=True,
        text=True,
    )


def _compile_target(tmp_path: Path, target: str) -> tuple[Path, Path]:
    mdl = tmp_path / "customer.mdl"
    sample = PROTOBUF_SAMPLE_MDL if target == "protobuf" else SAMPLE_MDL
    mdl.write_text(textwrap.dedent(sample).strip() + "\n", encoding="utf-8")

    out = tmp_path / "generated" / target
    result = CliRunner().invoke(
        cli,
        [
            "compile",
            str(mdl),
            "--target",
            target,
            "--out",
            str(out),
            "--registry",
            str(tmp_path / ".modelable" / "registry.db"),
            "--registry-ids",
            str(tmp_path / "registry-ids.lock"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (tmp_path / "registry-ids.lock").exists()
    return mdl, out


def _assert_docker_success(result: subprocess.CompletedProcess[str], target: str) -> None:
    assert result.returncode == 0, (
        f"{target} container build failed\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )


@pytest.mark.skipif(
    os.getenv("MODELABLE_DOCKER_SMOKE") != "1",
    reason="set MODELABLE_DOCKER_SMOKE=1 to run the Docker-based codegen smoke tests",
)
@pytest.mark.skipif(not _docker_available(), reason="docker is required for generated-language smoke tests")
@pytest.mark.parametrize("target,image,tool", TARGETS)
def test_codegen_backends_compile_inside_docker(tmp_path, target: str, image: str, tool: str) -> None:
    _, out = _compile_target(tmp_path, target)

    if target == "csharp":
        _write_csharp_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "dotnet build Smoke.csproj -nologo",
        )
        _assert_docker_success(result, target)
        return

    if target == "java":
        _write_java_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "javac -d build $(find . -name '*.java') && java -cp build customer.Smoke",
        )
        _assert_docker_success(result, target)
        return

    if target == "python":
        _write_python_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "/usr/local/bin/python smoke.py",
        )
        _assert_docker_success(result, target)
        return

    if target == "rust":
        _write_rust_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "/usr/local/cargo/bin/cargo test --quiet",
        )
        _assert_docker_success(result, target)
        return

    if target == "go":
        _write_go_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "/usr/local/go/bin/go test ./...",
        )
        _assert_docker_success(result, target)
        return

    if target == "typescript":
        _write_typescript_smoke(tmp_path, out)
        result = _run_docker(
            tmp_path,
            image,
            "/usr/local/bin/npx --yes -p typescript@5.9.2 tsc -p tsconfig.json",
        )
        _assert_docker_success(result, target)
        return

    if target == "protobuf":
        result = _run_docker(
            tmp_path,
            image,
            "apt-get update >/dev/null"
            " && apt-get install -y --no-install-recommends protobuf-compiler >/dev/null"
            " && find generated/protobuf -name '*.proto' -print0"
            " | xargs -0 protoc -I generated/protobuf"
            " --descriptor_set_out=/tmp/modelable.pb --include_imports",
        )
        _assert_docker_success(result, target)
        return

    raise AssertionError(f"Unhandled target: {target}")


def _write_python_smoke(tmp_path: Path, out: Path) -> None:
    smoke = tmp_path / "smoke.py"
    smoke.write_text(
        textwrap.dedent(
            f"""
            from __future__ import annotations

            import importlib.util
            from pathlib import Path
            from uuid import UUID


            ROOT = Path(__file__).resolve().parent


            def load_module(path: Path, name: str):
                spec = importlib.util.spec_from_file_location(name, path)
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                import sys
                sys.modules[name] = module
                spec.loader.exec_module(module)
                return module


            customer = load_module(ROOT / "generated" / "python" / "customer" / "customer_customer_v1.py", "customer_customer_v1")
            customer_view = load_module(ROOT / "generated" / "python" / "customer" / "customer_customer_view_v1.py", "customer_customer_view_v1")

            customer_obj = customer.CustomerCustomerV1(
                customerId=UUID("{SMOKE_UUID}"),
                displayName="Alice",
                tags=["vip"],
                nickname="ally",
                metadata={{"score": 7}},
                address=customer.CustomerCustomerV1Address(line1="Main", line2="Suite 1"),
            )
            view_obj = customer_view.CustomerCustomerViewV1(
                customerId=UUID("{SMOKE_UUID}"),
                displayName="Alice",
                tags=["vip"],
                nickname="ally",
                metadata={{"score": 7}},
                address=customer_view.CustomerCustomerViewV1Address(line1="Main", line2="Suite 1"),
            )

            assert customer_obj.displayName == "Alice"
            assert view_obj.address.line1 == "Main"
            assert view_obj.metadata["score"] == 7
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_csharp_smoke(tmp_path: Path, out: Path) -> None:
    (tmp_path / "Smoke.csproj").write_text(
        textwrap.dedent(
            """
            <Project Sdk="Microsoft.NET.Sdk">
              <PropertyGroup>
                <OutputType>Exe</OutputType>
                <TargetFramework>net10.0</TargetFramework>
                <Nullable>enable</Nullable>
                <ImplicitUsings>enable</ImplicitUsings>
                <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
              </PropertyGroup>
            <ItemGroup>
                <Compile Include="Program.cs" />
                <Compile Include="generated/csharp/**/*.cs" />
              </ItemGroup>
            </Project>
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "Program.cs").write_text(
        textwrap.dedent(
            f"""
            using System;
            using System.Collections.Generic;
            using Modelable.Customer;

            var customer = new CustomerCustomerV1
            {{
                CustomerId = Guid.Parse("{SMOKE_UUID}"),
                DisplayName = "Alice",
                Tags = new List<string> {{ "vip" }},
                Nickname = "ally",
                Metadata = new Dictionary<string, int> {{ ["score"] = 7 }},
                Address = new CustomerCustomerV1Address
                {{
                    Line1 = "Main",
                    Line2 = "Suite 1",
                }},
            }};

            var view = new CustomerCustomerViewV1
            {{
                CustomerId = Guid.Parse("{SMOKE_UUID}"),
                DisplayName = "Alice",
                Tags = new List<string> {{ "vip" }},
                Nickname = "ally",
                Metadata = new Dictionary<string, int> {{ ["score"] = 7 }},
                Address = new CustomerCustomerViewV1Address
                {{
                    Line1 = "Main",
                    Line2 = "Suite 1",
                }},
            }};

            Console.WriteLine(customer.DisplayName + " / " + view.DisplayName);
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_java_smoke(tmp_path: Path, out: Path) -> None:
    customer_dir = tmp_path / "customer"
    customer_dir.mkdir(parents=True, exist_ok=True)
    (customer_dir / "Smoke.java").write_text(
        textwrap.dedent(
            f"""
            package customer;

            import java.util.List;
            import java.util.Map;
            import java.util.Optional;
            import java.util.UUID;

            public final class Smoke {{
              public static void main(String[] args) {{
                var customer = new CustomerV1(
                  UUID.fromString("{SMOKE_UUID}"),
                  "Alice",
                  List.of("vip"),
                  Optional.of("ally"),
                  Optional.of(Map.of("score", 7L)),
                  Optional.of(new CustomerV1.Address("Main", Optional.of("Suite 1")))
                );

                var view = new CustomerViewV1(
                  UUID.fromString("{SMOKE_UUID}"),
                  "Alice",
                  List.of("vip"),
                  Optional.of("ally"),
                  Optional.of(Map.of("score", 7L)),
                  Optional.of(new CustomerViewV1.Address("Main", Optional.of("Suite 1")))
                );

                if (!customer.displayName().equals(view.displayName())) {{
                  throw new IllegalStateException("generated records did not preserve the expected fields");
                }}
              }}
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_rust_smoke(tmp_path: Path, out: Path) -> None:
    (tmp_path / "Cargo.toml").write_text(
        textwrap.dedent(
            """
            [package]
            name = "modelable_codegen_smoke"
            version = "0.1.0"
            edition = "2024"

            [dependencies]
            serde = { version = "1", features = ["derive"] }
            uuid = { version = "1", features = ["v4", "serde"] }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "lib.rs").write_text(
        textwrap.dedent(
            """
            #[path = "../generated/rust/customer/customer_customer_v1.rs"]
            pub mod customer_customer_v1;
            #[path = "../generated/rust/customer/customer_customer_view_v1.rs"]
            pub mod customer_customer_view_v1;

            #[cfg(test)]
            mod smoke {
                use std::collections::HashMap;
                use uuid::Uuid;

                use super::customer_customer_v1::{CustomerCustomerV1, CustomerCustomerV1Address};
                use super::customer_customer_view_v1::{CustomerCustomerViewV1, CustomerCustomerViewV1Address};

                #[test]
                fn generated_structs_compile_and_instantiate() {
                    let mut metadata = HashMap::new();
                    metadata.insert(String::from("score"), 7);

                    let uid = Uuid::parse_str("123e4567-e89b-12d3-a456-426614174000").unwrap();

                    let customer = CustomerCustomerV1 {
                        customer_id: uid,
                        display_name: String::from("Alice"),
                        tags: vec![String::from("vip")],
                        nickname: Some(String::from("ally")),
                        metadata: Some(metadata.clone()),
                        address: Some(CustomerCustomerV1Address {
                            line1: String::from("Main"),
                            line2: Some(String::from("Suite 1")),
                        }),
                    };

                    let view = CustomerCustomerViewV1 {
                        customer_id: uid,
                        display_name: String::from("Alice"),
                        tags: vec![String::from("vip")],
                        nickname: Some(String::from("ally")),
                        metadata: Some(metadata),
                        address: Some(CustomerCustomerViewV1Address {
                            line1: String::from("Main"),
                            line2: Some(String::from("Suite 1")),
                        }),
                    };

                    assert_eq!(customer.display_name, view.display_name);
                    assert_eq!(CustomerCustomerV1::SCHEMA_VERSION, 1);
                    assert_eq!(CustomerCustomerV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
                    assert_eq!(CustomerCustomerViewV1::SCHEMA_VERSION, 1);
                    assert_eq!(CustomerCustomerViewV1::SCHEMA_CONTENT_SIGNATURE.len(), 32);
                }
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_go_smoke(tmp_path: Path, out: Path) -> None:
    (tmp_path / "go.mod").write_text(
        textwrap.dedent(
            """
            module example.com/modelable-smoke

            go 1.26
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    customer_dir = tmp_path / "generated" / "go" / "customer"
    customer_dir.mkdir(parents=True, exist_ok=True)
    (customer_dir / "smoke_test.go").write_text(
        textwrap.dedent(
            f"""
            package customer

            import "testing"

            func TestGeneratedStructsCompileAndInstantiate(t *testing.T) {{
                customer := CustomerCustomerV1{{
                    CustomerId: "{SMOKE_UUID}",
                    DisplayName: "Alice",
                    Tags: []string{{"vip"}},
                    Nickname: ptrString("ally"),
                    Metadata: ptrMapStringInt64(map[string]int64{{"score": 7}}),
                    Address: &CustomerCustomerV1Address{{
                        Line1: "Main",
                        Line2: ptrString("Suite 1"),
                    }},
                }}

                view := CustomerCustomerViewV1{{
                    CustomerId: "{SMOKE_UUID}",
                    DisplayName: "Alice",
                    Tags: []string{{"vip"}},
                    Nickname: ptrString("ally"),
                    Metadata: ptrMapStringInt64(map[string]int64{{"score": 7}}),
                    Address: &CustomerCustomerViewV1Address{{
                        Line1: "Main",
                        Line2: ptrString("Suite 1"),
                    }},
                }}

                if customer.DisplayName != view.DisplayName {{
                    t.Fatalf("generated structs did not preserve the expected fields")
                }}
            }}

            func ptrString(value string) *string {{
                return &value
            }}

            func ptrMapStringInt64(value map[string]int64) *map[string]int64 {{
                return &value
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def _write_typescript_smoke(tmp_path: Path, out: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        textwrap.dedent(
            """
            {
              "compilerOptions": {
                "target": "ES2022",
                "module": "ES2022",
                "moduleResolution": "Node",
                "strict": true,
                "noEmit": true,
                "skipLibCheck": true
              },
              "include": ["smoke.ts", "generated/typescript/**/*.ts"]
            }
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "smoke.ts").write_text(
        textwrap.dedent(
            f"""
            import type {{ CustomerCustomerV1 }} from "./generated/typescript/customer.Customer.v1";
            import type {{ CustomerCustomerViewV1 }} from "./generated/typescript/customer.CustomerView.v1";

            const customer: CustomerCustomerV1 = {{
              customerId: "{SMOKE_UUID}",
              displayName: "Alice",
              tags: ["vip"],
              nickname: "ally",
              metadata: {{ score: 7 }},
              address: {{ line1: "Main", line2: "Suite 1" }},
            }};

            const view: CustomerCustomerViewV1 = {{
              customerId: "{SMOKE_UUID}",
              displayName: "Alice",
              tags: ["vip"],
              nickname: "ally",
              metadata: {{ score: 7 }},
              address: {{ line1: "Main", line2: "Suite 1" }},
            }};

            if (customer.displayName !== view.displayName) {{
              throw new Error("generated interfaces did not preserve the expected fields");
            }}
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
