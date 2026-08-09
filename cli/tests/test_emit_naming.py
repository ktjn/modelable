from modelable.emitters.naming import pascalize_plain, pascalize_titlecase, snake_case


def test_pascalize_titlecase_titlecases_all_uppercase_tokens():
    assert pascalize_titlecase("INTERNAL") == "Internal"
    assert pascalize_titlecase("SERVER_CLIENT") == "ServerClient"
    assert pascalize_titlecase("AlreadyPascalCase") == "AlreadyPascalCase"
    assert pascalize_titlecase("camelCase") == "CamelCase"


def test_pascalize_plain_capitalizes_without_lowercasing_uppercase_tokens():
    assert pascalize_plain("INTERNAL") == "INTERNAL"
    assert pascalize_plain("server_client") == "ServerClient"
    assert pascalize_plain("AlreadyPascalCase") == "AlreadyPascalCase"
    assert pascalize_plain("camelCase") == "CamelCase"


def test_pascalize_variants_fall_back_when_empty():
    assert pascalize_titlecase("") == "Generated"
    assert pascalize_plain("") == "Generated"
    assert pascalize_plain("", fallback="") == ""


def test_snake_case_lowercases_and_underscores():
    assert snake_case("CustomerViewV1") == "customer_view_v1"
    assert snake_case("displayName") == "display_name"
    assert (
        snake_case(
            "_",
        )
        == "generated"
    )
