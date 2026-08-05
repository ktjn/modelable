from modelable.emitters.targets import CODEGEN_TARGETS, get_codegen_target, list_compat_checkable_targets


def test_protobuf_and_grpc_support_compat_check():
    assert get_codegen_target("protobuf").supports_compat_check is True
    assert get_codegen_target("grpc").supports_compat_check is True


def test_other_targets_do_not_support_compat_check():
    non_compat_targets = [target for target in CODEGEN_TARGETS if target.name not in ("protobuf", "grpc")]
    assert non_compat_targets
    assert all(target.supports_compat_check is False for target in non_compat_targets)


def test_list_compat_checkable_targets_returns_exactly_protobuf_and_grpc():
    names = {target.name for target in list_compat_checkable_targets()}
    assert names == {"protobuf", "grpc"}
