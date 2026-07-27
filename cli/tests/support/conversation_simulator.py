from __future__ import annotations

import json
import re

from modelable.llm.provider_types import LLMRequest, LLMResponse


class ConversationSimulatorProvider:
    def __init__(
        self,
        *,
        malformed_first: bool = False,
        failure: str | None = None,
    ) -> None:
        self.malformed_first = malformed_first
        self.failure = failure
        self.requests: list[LLMRequest] = []

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.failure is not None:
            raise RuntimeError(self.failure)
        if request.response_format == "text":
            return LLMResponse(
                content=_answer_for(request.user),
                provider="simulator",
                model="semantic-v1",
            )
        if (
            self.malformed_first
            and len(self.requests) == 1
            and "Previous response validation error" not in request.user
        ):
            content = "{malformed"
        else:
            content = json.dumps(_plan_for(_user_request(request.user)))
        return LLMResponse(
            content=content,
            provider="simulator",
            model="semantic-v1",
        )


def _user_request(prompt: str) -> str:
    match = re.search(
        r"User request:\n(?P<message>.*?)(?:\n\nPrevious response validation error:|\Z)",
        prompt,
        flags=re.DOTALL,
    )
    return match.group("message").strip() if match is not None else prompt.strip()


def _answer_for(user_prompt: str) -> str:
    facts_match = re.search(
        r"Workspace facts:\n(?P<facts>.*?)\n\nUser question:\n(?P<question>.*?)$",
        user_prompt,
        flags=re.DOTALL,
    )
    if facts_match is None:
        return "Here is what I found in the workspace."
    facts = facts_match.group("facts").strip()
    question = facts_match.group("question").strip()
    return f"Based on the workspace facts, here is the answer to '{question}':\n\n{facts}"


def _plan_for(message: str) -> dict[str, object]:
    normalized = message.lower()
    if "describe the workspace" in normalized:
        return {
            "kind": "query",
            "query_kind": "summary",
            "refs": [],
            "question": message,
        }
    if "create an invoice" in normalized:
        return {
            "kind": "change_set",
            "summary": "Create billing.Invoice@1",
            "operations": [
                {
                    "kind": "create_model",
                    "domain": "billing",
                    "name": "Invoice",
                    "model_kind": "entity",
                    "fields": [
                        {
                            "name": "invoiceId",
                            "type": {"kind": "uuid"},
                            "annotations": [{"kind": "key"}],
                        }
                    ],
                }
            ],
        }
    if "suggest a projection" in normalized:
        return {
            "kind": "change_set",
            "summary": "Create billing.CustomerProjection@1",
            "operations": [
                {
                    "kind": "create_projection",
                    "domain": "billing",
                    "name": "CustomerProjection",
                    "source": {
                        "model": "customer.Customer",
                        "version": 1,
                        "alias": "customer",
                    },
                    "fields": [
                        {
                            "name": "customerId",
                            "mapping": {
                                "kind": "direct",
                                "source_alias": "customer",
                                "source_field": "customerId",
                            },
                        }
                    ],
                }
            ],
        }
    if "create a projection" in normalized:
        return {
            "kind": "clarification",
            "question": "Which source model and consumer domain should I use?",
            "reason": "A projection requires a grounded source and consumer.",
        }
    if "add email" in normalized:
        return {
            "kind": "change_set",
            "summary": "Add email to customer.Customer@2",
            "operations": [
                {
                    "kind": "append_model_version",
                    "source": "customer.Customer@1",
                    "version": 2,
                },
                {
                    "kind": "add_field",
                    "target": "customer.Customer@2",
                    "field": {
                        "name": "email",
                        "type": {"kind": "string"},
                    },
                },
            ],
        }
    if "/compile json-schema" in normalized:
        return {
            "kind": "compile",
            "target": "json-schema",
            "domains": [],
            "output": None,
            "descriptor_set": False,
            "summary": "Compile the workspace to JSON Schema.",
        }
    return {
        "kind": "unsupported",
        "request": message,
        "reason": "The semantic simulator has no fixture for this request.",
    }
