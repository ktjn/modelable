"""Guardrail for Slice D0's additive-syntax policy.

Slice D0 decided: old syntax never changes meaning; new semantics require
new syntax (docs/correction-and-capability-plan.md, Slice D0 Outcome). This
file pins the canonical signature and formatted output of a small,
representative set of already-shipped constructs to fixed expected values.
A future change that alters what any of these mean -- not just a bug, but
any accidental reinterpretation of historical syntax -- fails here first,
rather than being discovered later as a silent compatibility break.

These are deliberately exact-match assertions, not property tests: the
point is to notice *any* change, and require a deliberate, reviewed update
to this file's expected values when one is intentional.
"""

from __future__ import annotations

from modelable.compiler.render import render_mdl
from modelable.parser.parse import parse_text_to_ir
from modelable.planner.planner import expand_projection_selections
from modelable.registry.signature import compute_version_signature

PLAIN_ENTITY = """domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    name: string
    quantity: int
  }
}
"""

DEPRECATED_RENAME = """domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    @deprecated(replacedBy: "fullName") name: string
  }
  entity Widget @ 2 (additive) {
    @key widgetId: uuid
    fullName: string
  }
}
"""

REF_TYPE_FIELD = """domain platform {
  owner: "platform-team"
  entity Category @ 1 (additive) {
    @key categoryId: uuid
  }
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    categoryRef: ref<platform.Category @ 1>
  }
}
"""

INDEX_DECLARATION = """domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    categoryId: uuid
  }
  index Widget @ 1 {
    primary widgetId
    secondary byCategory {
      key: [categoryId]
      unique: false
    }
  }
}
"""

HAND_WRITTEN_PROJECTION = """domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    name: string
  }
  projection WidgetSummary @ 1
    from platform.Widget @ 1 as w
  {
    @key widgetId <- w.widgetId
    name <- w.name
  }
}
"""

PICK_PROJECTION = """domain platform {
  owner: "platform-team"
  entity Widget @ 1 (additive) {
    @key widgetId: uuid
    name: string
  }
  projection WidgetSummary @ 1
    from platform.Widget @ 1 as w
    pick(widgetId, name)
  {
  }
}
"""


def _model_version(mdl_text: str, model_name: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    domain = mdl.domains[0]
    return next(v for v in domain.models[model_name] if v.version == version)


def _projection_version(mdl_text: str, projection_name: str, version: int = 1):
    mdl = parse_text_to_ir(mdl_text)
    errors = expand_projection_selections(mdl)
    assert errors == [], errors
    domain = mdl.domains[0]
    return next(v for v in domain.projections[projection_name] if v.version == version)


def test_plain_entity_signature_is_pinned():
    version = _model_version(PLAIN_ENTITY, "Widget")
    signature = compute_version_signature("platform", "Widget", version)
    assert signature == "bfd33129e44f667cb51d329adb1f4215adf1d12fc62bf0be8936341486ed66eb"


def test_deprecated_rename_signatures_are_pinned():
    old = _model_version(DEPRECATED_RENAME, "Widget", version=1)
    new = _model_version(DEPRECATED_RENAME, "Widget", version=2)
    assert compute_version_signature("platform", "Widget", old) == (
        "697272125268e790d16ae3e2b7efc26d26f616b7db6e7d32fcb5f29fda7bbd26"
    )
    assert compute_version_signature("platform", "Widget", new) == (
        "4a65470dea7f2964c74364a855f537f2540a78c8daf10f9f4d7cf98ba4ab214a"
    )


def test_ref_type_field_signature_is_pinned():
    version = _model_version(REF_TYPE_FIELD, "Widget")
    signature = compute_version_signature("platform", "Widget", version)
    assert signature == "142069e18a50f58dedb62974f4378721b3335a950caff7e5b4621f4e12eb2ac0"


def test_hand_written_projection_signature_is_pinned():
    version = _projection_version(HAND_WRITTEN_PROJECTION, "WidgetSummary")
    signature = compute_version_signature("platform", "WidgetSummary", version)
    assert signature == "0965f08f1939dc937d813646111323fe64b7dc1e09ccc6606c35ebf6cdb64da8"


def test_pick_projection_signature_matches_hand_written_equivalent():
    picked = _projection_version(PICK_PROJECTION, "WidgetSummary")
    hand_written = _projection_version(HAND_WRITTEN_PROJECTION, "WidgetSummary")
    assert compute_version_signature("platform", "WidgetSummary", picked) == compute_version_signature(
        "platform", "WidgetSummary", hand_written
    )


def test_formatted_output_is_pinned():
    for text in (
        PLAIN_ENTITY,
        DEPRECATED_RENAME,
        REF_TYPE_FIELD,
        INDEX_DECLARATION,
        HAND_WRITTEN_PROJECTION,
        PICK_PROJECTION,
    ):
        mdl = parse_text_to_ir(text)
        rendered = render_mdl(mdl)
        assert rendered == text, f"formatted output drifted from pinned source:\n{rendered}"


def test_formatted_output_round_trips():
    for text in (
        PLAIN_ENTITY,
        DEPRECATED_RENAME,
        REF_TYPE_FIELD,
        INDEX_DECLARATION,
        HAND_WRITTEN_PROJECTION,
        PICK_PROJECTION,
    ):
        once = render_mdl(parse_text_to_ir(text))
        twice = render_mdl(parse_text_to_ir(once))
        assert once == twice
