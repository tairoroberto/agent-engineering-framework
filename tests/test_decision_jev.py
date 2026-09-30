from __future__ import annotations

import sys
import json
from pathlib import Path
import unittest
import socket
import urllib.error
import http.client
from unittest import mock
from dataclasses import replace

# Keep direct execution rooted at the repository so imports resolve the package
# under test rather than requiring PYTHONPATH to be set externally.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from state.decision import (
    BoundedDecisionContext,
    ChoiceQuestion,
    DecisionRequest,
    DecisionSchema,
    Fact,
    ProbabilityQuestion,
    ScoreQuestion,
)
from state.decision_jev import JevDecisionProvider, JevHttpConfig, build_payload, normalize_response
from state.decision_providers import ProviderError, ProviderFailure, ProviderStatus


class JevDecisionProviderTest(unittest.TestCase):
    def request(self) -> DecisionRequest:
        schema = DecisionSchema((
            ChoiceQuestion("task_type", ("bug", "feature", "maintenance", "unknown")),
            ScoreQuestion("complexity", (1, 2, 3, 4, 5)),
            ScoreQuestion("risk", (1, 2, 3, 4, 5)),
            ScoreQuestion("architectural_impact", (1, 2, 3, 4, 5)),
            *(ProbabilityQuestion(key) for key in (
                "requires_reasoning", "requires_review", "requires_qa",
                "requirements_clear", "security_sensitive",
            )),
        ))
        return DecisionRequest.from_context(
            schema,
            BoundedDecisionContext("classify", facts=(Fact("task_type", "bug"),)),
        )

    def post_request(self) -> DecisionRequest:
        request = self.request()
        schema = DecisionSchema(request.schema.questions + tuple(
            ProbabilityQuestion(key) for key in (
                "meaningful_progress", "requirements_satisfied",
                "another_iteration_useful", "requires_escalation",
            )
        ))
        return replace(request, phase="post_execution", schema=schema)

    def test_request_uses_canonical_pre_execution_schema(self) -> None:
        self.assertEqual(
            [question.key for question in self.request().schema.questions],
            [
                "task_type", "complexity", "risk", "architectural_impact",
                "requires_reasoning", "requires_review", "requires_qa",
                "requirements_clear", "security_sensitive",
            ],
        )

    def test_default_is_unavailable_without_calling_anything(self) -> None:
        provider = JevDecisionProvider(environ={}, opener=_Opener(error=AssertionError("network")))
        self.assertEqual(ProviderStatus.UNAVAILABLE, provider.capabilities().status)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.UNAVAILABLE, raised.exception.category)

    def test_validates_request_before_transport(self) -> None:
        calls = []
        provider = JevDecisionProvider(lambda request: calls.append(request), lambda payload, request: payload,
                                       environ={}, opener=_FailFastOpener())
        request = self.request()
        object.__setattr__(request, "phase", "invalid")
        with self.assertRaises(ValueError):
            provider.evaluate(request)
        self.assertEqual([], calls)

    def test_injected_transport_is_mapped_to_central_result(self) -> None:
        request = self.request()
        payload = {
            "answers": [
                {"key": "task_type", "value": "bug", "status": "answered", "confidence": 1.0, "provider_id": "jev"},
                *[
                    {"key": key, "value": value, "status": "answered", "confidence": 1.0, "provider_id": "jev"}
                    for key, value in (
                        ("complexity", 1),
                        ("risk", 1),
                        ("architectural_impact", 1),
                        ("requires_reasoning", 0.0),
                        ("requires_review", 0.0),
                        ("requires_qa", 0.0),
                        ("requirements_clear", 1.0),
                        ("security_sensitive", 0.0),
                    )
                ],
            ],
            "schema_version": 1,
        }
        provider = JevDecisionProvider(lambda value: payload, lambda value, request: value,
                                       environ={}, opener=_FailFastOpener())
        result = provider.evaluate(request)
        self.assertEqual("bug", result.answers[0].value)

    def test_invalid_mapped_payload_is_bounded_provider_failure(self) -> None:
        provider = JevDecisionProvider(lambda request: {}, lambda payload, request: payload,
                                       environ={}, opener=_FailFastOpener())
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.INVALID, raised.exception.category)

    def test_unexpected_transport_exception_is_error(self) -> None:
        provider = JevDecisionProvider(lambda request: (_ for _ in ()).throw(RuntimeError("offline")), lambda payload, request: payload,
                                       environ={}, opener=_FailFastOpener())
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.ERROR, raised.exception.category)

    def test_declared_transport_provider_error_is_preserved(self) -> None:
        expected = ProviderError(ProviderFailure.TIMEOUT)
        provider = JevDecisionProvider(lambda request: (_ for _ in ()).throw(expected), lambda payload, request: payload,
                                       environ={}, opener=_FailFastOpener())
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertIs(expected, raised.exception)

    def test_unexpected_mapper_exception_is_invalid(self) -> None:
        provider = JevDecisionProvider(lambda request: {}, lambda payload, request: (_ for _ in ()).throw(RuntimeError("bad map")),
                                       environ={}, opener=_FailFastOpener())
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.INVALID, raised.exception.category)

    def test_canonical_fixtures_are_complete(self) -> None:
        root = Path(__file__).parent / "fixtures" / "decision"
        request = json.loads((root / "jev-http-request.json").read_text())
        response = json.loads((root / "jev-http-response.json").read_text())
        self.assertEqual(request["pre_execution"], build_payload(self.request()))
        self.assertEqual(request["post_execution"], build_payload(self.post_request()))
        self.assertEqual(set(response["answers"]), set(request["pre_execution"]["questions"]))
        normalize_response(response, self.request())

    def test_golden_criteria_are_distinct_meaningful_canonical_descriptions(self) -> None:
        request = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-request.json").read_text())["pre_execution"]
        descriptions = {key: value["instructions"] for key, value in request["questions"].items()}
        self.assertEqual(len(descriptions), len(set(descriptions.values())))
        for description in descriptions.values():
            self.assertIsInstance(description, str)
            self.assertGreater(len(description.strip()), 10)
        criteria = request["questions"]["task_type"]["criteria"]
        self.assertEqual(len(criteria), len(set(criteria.values())))
        self.assertTrue(all(isinstance(value, str) and len(value.strip()) > 10 for value in criteria.values()))

    def test_endpoint_and_timeout_are_bounded(self) -> None:
        with self.assertRaises(ValueError): JevHttpConfig("https://user:pass@example.test").validate()
        with self.assertRaises(ValueError): JevHttpConfig("https://example.test?x=1").validate()
        with self.assertRaises(ValueError): JevHttpConfig(timeout_seconds=0.01).validate()
        with self.assertRaises(ValueError): JevHttpConfig(timeout_seconds=31).validate()

    def test_key_whitespace_is_unavailable_without_network(self) -> None:
        provider = JevDecisionProvider(environ={"TYPESAFE_API_KEY": "bad key"}, opener=object())
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.UNAVAILABLE, raised.exception.category)

    def test_transport_only_provider_is_unsupported_without_http(self) -> None:
        opener = _Opener(error=AssertionError("network"))
        provider = JevDecisionProvider(transport=lambda request: {}, environ={}, opener=opener)
        self.assertEqual(ProviderStatus.UNAVAILABLE, provider.capabilities().status)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.UNSUPPORTED, raised.exception.category)
        self.assertEqual([], opener.calls)

    def test_mapper_only_provider_is_unsupported_without_http(self) -> None:
        opener = _Opener(error=AssertionError("network"))
        provider = JevDecisionProvider(mapper=lambda payload, request: {}, environ={}, opener=opener)
        self.assertEqual(ProviderStatus.UNAVAILABLE, provider.capabilities().status)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.UNSUPPORTED, raised.exception.category)
        self.assertEqual([], opener.calls)


class _Response:
    def __init__(self, body=b"", status=200, headers=None, error=None):
        self.body, self.status = body, status
        self.headers = headers or {"Content-Type": "application/json"}
        self.error = error
        self.closed = False
        self.close_count = 0

    def read(self, limit=None):
        if self.error:
            raise self.error
        return self.body if limit is None else self.body[:limit]

    def close(self):
        self.closed = True
        self.close_count += 1

    def getcode(self):
        return self.status


class _FailFastOpener:
    def open(self, request, timeout):
        raise AssertionError("unexpected real HTTP transport")


class _Opener:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self.response


class JevHttpContractTest(JevDecisionProviderTest):
    def http_provider(self, response=None, error=None, environ=None, **config):
        opener = _Opener(response, error)
        provider = JevDecisionProvider(
            config=JevHttpConfig(endpoint="https://example.test/v1/systemone", **config),
            environ=environ or {"TYPESAFE_API_KEY": "test-key"}, opener=opener,
        )
        return provider, opener

    def test_default_empty_environment_never_opens_network(self):
        opener = _Opener(error=AssertionError("network"))
        provider = JevDecisionProvider(environ={}, opener=opener)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.UNAVAILABLE, raised.exception.category)
        self.assertEqual([], opener.calls)

    def test_reordered_canonical_schemas_fail_before_opening(self):
        for request in (self.request(), self.post_request()):
            with self.subTest(phase=request.phase):
                reordered = replace(request, schema=replace(request.schema, questions=tuple(reversed(request.schema.questions))))
                provider, opener = self.http_provider()
                with self.assertRaises(ProviderError) as raised:
                    provider.evaluate(reordered)
                self.assertEqual(ProviderFailure.INVALID, raised.exception.category)
                self.assertEqual([], opener.calls)

    def test_opener_runtime_error_is_sanitized_and_called_once(self):
        api_key = "T002-API-KEY-SENTINEL"
        body = "T002-BODY-SENTINEL"
        opener = _Opener(error=RuntimeError(f"{api_key} {body}"))
        provider = JevDecisionProvider(
            config=JevHttpConfig(endpoint="https://example.test/v1/systemone"),
            environ={"TYPESAFE_API_KEY": api_key}, opener=opener,
        )
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.ERROR, raised.exception.category)
        self.assertNotIn(api_key, str(raised.exception))
        self.assertNotIn(body, str(raised.exception))
        self.assertEqual(1, len(opener.calls))

    def test_http_request_matches_golden_and_transport_contract(self):
        body = (Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_bytes()
        provider, opener = self.http_provider(_Response(body))
        with mock.patch("state.decision_jev.time.monotonic", side_effect=(10.0, 10.0075)):
            evaluation = provider.evaluate(self.request())
        self.assertEqual(1, len(opener.calls))
        request, timeout = opener.calls[0]
        golden = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-request.json").read_text())["pre_execution"]
        self.assertEqual("https://example.test/v1/systemone", request.full_url)
        self.assertEqual("POST", request.method)
        self.assertEqual("Bearer test-key", request.get_header("Authorization"))
        self.assertEqual("application/json", request.get_header("Content-type"))
        self.assertEqual(json.dumps(golden, separators=(",", ":"), ensure_ascii=True).encode(), request.data)
        self.assertEqual(10.0, timeout)
        self.assertEqual(7, evaluation.metadata.latency_ms)
        self.assertEqual(1, opener.response.close_count)

    def test_post_http_request_matches_golden_and_transport_contract(self):
        payload = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_text())
        for key in ("meaningful_progress", "requirements_satisfied", "another_iteration_useful", "requires_escalation"):
            payload["answers"][key] = {"type": "noul", "noul": 0.5}
        body = json.dumps(payload, separators=(",", ":")).encode()
        provider, opener = self.http_provider(_Response(body))
        with mock.patch("state.decision_jev.time.monotonic", side_effect=(20.0, 20.012)):
            evaluation = provider.evaluate(self.post_request())
        request, timeout = opener.calls[0]
        golden = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-request.json").read_text())["post_execution"]
        self.assertEqual(json.dumps(golden, separators=(",", ":"), ensure_ascii=True).encode(), request.data)
        self.assertEqual(12, evaluation.metadata.latency_ms)
        self.assertEqual(10.0, timeout)
        self.assertEqual(1, opener.response.close_count)

    def test_statuses_and_redirects_are_classified_without_following(self):
        for status, failure in ((301, ProviderFailure.ERROR), (401, ProviderFailure.UNAVAILABLE),
                                (422, ProviderFailure.INVALID), (429, ProviderFailure.UNAVAILABLE),
                                (529, ProviderFailure.UNAVAILABLE), (500, ProviderFailure.ERROR)):
            with self.subTest(status=status):
                response = _Response(status=status)
                provider, opener = self.http_provider(response)
                with self.assertRaises(ProviderError) as raised:
                    provider.evaluate(self.request())
                self.assertEqual(failure, raised.exception.category)
                self.assertEqual(1, len(opener.calls))
                self.assertEqual(1, response.close_count)

    def test_transport_failures_and_response_close(self):
        cases = ((TimeoutError(), ProviderFailure.TIMEOUT), (socket.timeout(), ProviderFailure.TIMEOUT),
                 (urllib.error.URLError("offline"), ProviderFailure.ERROR),
                 (OSError("read"), ProviderFailure.ERROR),
                 (http.client.HTTPException("protocol"), ProviderFailure.ERROR),
                  (urllib.error.URLError(socket.timeout("timeout")), ProviderFailure.TIMEOUT),
                  (urllib.error.URLError(ConnectionError("connection")), ProviderFailure.ERROR),
                  (ConnectionError("connection"), ProviderFailure.ERROR), (OSError("read"), ProviderFailure.ERROR),
                  (http.client.HTTPException("protocol"), ProviderFailure.ERROR),
                  (http.client.IncompleteRead(b"partial"), ProviderFailure.ERROR))
        for error, failure in cases:
            with self.subTest(type=type(error).__name__):
                response = _Response(error=error)
                provider, opener = self.http_provider(response=response)
                with self.assertRaises(ProviderError) as raised:
                    provider.evaluate(self.request())
                self.assertEqual(failure, raised.exception.category)
                self.assertEqual(1, len(opener.calls))
                self.assertEqual(1, response.close_count)
        response = _Response(b"not-json")
        provider, _ = self.http_provider(response)
        with self.assertRaises(ProviderError): provider.evaluate(self.request())
        self.assertTrue(response.closed)
        self.assertEqual(1, response.close_count)

    def test_http_errors_are_classified_and_sanitized(self):
        for status, failure in ((401, ProviderFailure.UNAVAILABLE), (422, ProviderFailure.INVALID),
                                (429, ProviderFailure.UNAVAILABLE), (529, ProviderFailure.UNAVAILABLE),
                                (500, ProviderFailure.ERROR)):
            with self.subTest(status=status):
                response = _Response()
                error = urllib.error.HTTPError("https://example.test", status, "sentinel-body", {}, response)
                provider, opener = self.http_provider(error=error)
                with self.assertRaises(ProviderError) as raised:
                    provider.evaluate(self.request())
                self.assertEqual(failure, raised.exception.category)
                self.assertNotIn("sentinel", str(raised.exception))
                self.assertEqual(1, len(opener.calls))
                self.assertEqual(1, response.close_count)

    def test_close_failure_is_error_without_leaking_details(self):
        response = _Response()
        response.close = lambda: (_ for _ in ()).throw(OSError("close-sentinel"))
        provider, opener = self.http_provider(response)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.ERROR, raised.exception.category)
        self.assertNotIn("close-sentinel", str(raised.exception))
        self.assertEqual(1, len(opener.calls))

    def test_weighted_score_mismatch_is_invalid(self):
        payload = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_text())
        payload["answers"]["complexity"]["score"] = 2
        with self.assertRaises(ProviderError) as raised:
            normalize_response(payload, self.request())
        self.assertEqual(ProviderFailure.INVALID, raised.exception.category)

    def test_content_and_body_bounds_are_rejected(self):
        cases = [({"Content-Type": "text/plain"}, b"{}"),
                 ({"Content-Type": "application/json", "Content-Length": "bad"}, b"{}"),
                 ({"Content-Type": "application/json", "Content-Length": "-1"}, b"{}"),
                 ({"Content-Type": "application/json", "Content-Length": str(1024 * 1024 + 1)}, b"{}"),
                 ({"Content-Type": "application/json"}, b"x" * (1024 * 1024 + 1)),
                  ({"Content-Type": "application/json"}, b"\xff")]
        for headers, body in cases:
            with self.subTest(headers=headers, size=len(body)):
                provider, _ = self.http_provider(_Response(body, headers=headers))
                with self.assertRaises(ProviderError) as raised: provider.evaluate(self.request())
                self.assertEqual(ProviderFailure.INVALID, raised.exception.category)
        response = _Response(b'{"model":"x"}', headers={"Content-Type": "application/json", "Content-Length": "1"})
        provider, opener = self.http_provider(response)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.INVALID, raised.exception.category)
        self.assertEqual(1, len(opener.calls))
        self.assertEqual(1, response.close_count)

    def test_duplicate_json_and_fixture_invalid_payload_fail(self):
        duplicate = b'{"model":"x","model":"y"}'
        provider, _ = self.http_provider(_Response(duplicate))
        with self.assertRaises(ProviderError): provider.evaluate(self.request())
        invalid = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-invalid.json").read_text())
        with self.assertRaises(ProviderError): normalize_response(invalid, self.request())

    def test_valid_response_exposes_all_normalized_values_and_metadata(self):
        payload = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_text())
        evaluation = normalize_response(payload, self.request(), elapsed_ms=7)
        self.assertEqual("jev-1.13.0", evaluation.metadata.model)
        self.assertEqual((100, 100), (evaluation.metadata.usage.input_tokens, evaluation.metadata.usage.output_tokens))
        self.assertIsInstance(evaluation.metadata.latency_ms, int)
        self.assertEqual(["bug", 2, 3, 2, 0.25, 0.0, 0.0, 1.0, 0.25],
                         [answer.value for answer in evaluation.result.answers])
        self.assertEqual([1.0, 0.5, 0.5, 1.0, 0.5, 1.0, 1.0, 1.0, 0.5],
                         [answer.confidence for answer in evaluation.result.answers])

    def test_no_redirect_handler_does_not_follow(self):
        from state.decision_jev import _NoRedirectHandler
        request = urllib.request.Request("https://example.test")
        self.assertIsNone(_NoRedirectHandler().redirect_request(request, None, 302, "redirect", {}, "https://other.test"))

    def test_response_schema_mutations_are_all_invalid(self):
        base = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_text())
        mutations = []

        def mutate_answer(key, **changes):
            value = dict(base)
            value["answers"] = dict(base["answers"])
            answer = dict(base["answers"][key])
            answer.update(changes)
            value["answers"][key] = answer
            mutations.append(value)

        def reordered_answer(key, fields):
            value = dict(base)
            value["answers"] = dict(base["answers"])
            answer = base["answers"][key]
            value["answers"][key] = {field: answer[field] for field in fields}
            mutations.append(value)

        mutations += [dict(base, **{key: value}) for key, value in (
            ("extra", 1), ("model", None), ("answers", None), ("usage", None),
        )]
        mutations += [
            {"answers": base["answers"], "model": base["model"], "usage": base["usage"]},
            {"model": base["model"], "usage": base["usage"], "answers": base["answers"]},
            dict(base, answers=dict(reversed(list(base["answers"].items())))),
            dict(base, usage={"output_tokens": 100, "input_tokens": 100}),
        ]
        mutations += [
            dict(base, model=value) for value in (1, " ", True, "x" * 256)
        ]
        for value in (
            {"input_tokens": 1, "output_tokens": 1, "extra": 1},
            {"input_tokens": "1", "output_tokens": 1},
            {"input_tokens": True, "output_tokens": 1},
            {"input_tokens": -1, "output_tokens": 1},
            {"input_tokens": 1},
            {"input_tokens": 1, "output_tokens": 1.0},
            {"input_tokens": 1, "output_tokens": True},
            {"input_tokens": 1, "output_tokens": -1},
            {"input_tokens": 1, "output_tokens": 1_000_001},
            {"input_tokens": 1_000_001, "output_tokens": 1},
        ):
            mutations.append(dict(base, usage=value))
        missing = dict(base["answers"])
        del missing["task_type"]
        mutations.append(dict(base, answers=missing))
        extra = dict(base["answers"], extra_question=base["answers"]["task_type"])
        mutations.append(dict(base, answers=extra))

        choice = base["answers"]["task_type"]
        mutate_answer("task_type", type="score")
        mutate_answer("task_type", selection=1)
        mutate_answer("task_type", selection="not-a-choice")
        mutate_answer("task_type", confidence="1")
        mutate_answer("task_type", confidence=float("nan"))
        mutate_answer("task_type", confidence=-0.1)
        mutate_answer("task_type", confidence=1.1)
        reordered_answer("task_type", ("probabilities", "confidence", "selection", "type"))
        for probabilities in (
            {"bug": 1, "feature": 0, "maintenance": 0},
            {**choice["probabilities"], "bug": 2},
            {**choice["probabilities"], "bug": 0.5},
            {key: "0" for key in choice["probabilities"]},
        ):
            value = dict(base); value["answers"] = dict(base["answers"]); value["answers"]["task_type"] = dict(choice, probabilities=probabilities); mutations.append(value)
        score = dict(base["answers"]["complexity"])
        mutate_answer("complexity", type="choice")
        mutate_answer("complexity", score="0.5")
        mutate_answer("complexity", score=float("nan"))
        mutate_answer("complexity", score=-0.1)
        mutate_answer("complexity", score=4.1)
        reordered_answer("complexity", ("probabilities", "confidence", "legend", "score", "type"))
        for change in (
            dict(score, confidence="x"), dict(score, confidence=2), dict(score, score=2),
            dict(score, legend={"0": "bad"}), dict(score, legend=None),
            dict(score, legend={**score["legend"], "0": 1}),
            dict(score, probabilities={"0": 1}),
            dict(score, probabilities={**score["probabilities"], "0": float("nan")}),
            dict(score, probabilities={**score["probabilities"], "0": 2}),
            dict(score, probabilities={**score["probabilities"], "1": 0}),
            dict(score, probabilities={key: "0" for key in score["probabilities"]}),
        ):
            value = dict(base); value["answers"] = dict(base["answers"]); value["answers"]["complexity"] = change; mutations.append(value)
        mutate_answer("requires_reasoning", type="score")
        mutate_answer("requires_reasoning", noul="x")
        mutate_answer("requires_reasoning", noul=float("nan"))
        mutate_answer("requires_reasoning", noul=-0.1)
        mutate_answer("requires_reasoning", noul=1.1)
        reordered_answer("requires_reasoning", ("noul", "type"))
        for change in (
            dict(base["answers"]["requires_reasoning"], extra=1),
            {"type": "noul"},
        ):
            value = dict(base); value["answers"] = dict(base["answers"]); value["answers"]["requires_reasoning"] = change; mutations.append(value)
        self.assertEqual(61, len(mutations))
        for payload in mutations:
            with self.subTest(payload=payload):
                with self.assertRaises(ProviderError) as raised:
                    normalize_response(payload, self.request())
                self.assertEqual(ProviderFailure.INVALID, raised.exception.category)

    def test_deeply_nested_json_is_invalid_without_leaking_body(self):
        body = b"[" * 5000 + b"]" * 5000
        response = _Response(body)
        provider, opener = self.http_provider(response)
        with self.assertRaises(ProviderError) as raised:
            provider.evaluate(self.request())
        self.assertEqual(ProviderFailure.INVALID, raised.exception.category)
        self.assertNotIn(body.decode(), str(raised.exception))
        self.assertEqual(1, len(opener.calls))
        self.assertEqual(1, response.close_count)

    def test_model_sentinel_is_rejected_without_leaking_to_failure_or_result(self):
        sentinel = "T002-SENTINEL-API-KEY"
        base = json.loads((Path(__file__).parent / "fixtures/decision/jev-http-response.json").read_text())
        for model in (sentinel, f"jev-response-{sentinel}-suffix"):
            with self.subTest(model=model):
                payload = dict(base, model=model)
                response = _Response(json.dumps(payload).encode())
                provider, opener = self.http_provider(
                    response, environ={"TYPESAFE_API_KEY": sentinel},
                )
                with self.assertRaises(ProviderError) as raised:
                    provider.evaluate(self.request())
                self.assertEqual(ProviderFailure.INVALID, raised.exception.category)
                self.assertNotIn(sentinel, str(raised.exception))
                self.assertEqual(1, len(opener.calls))
                self.assertEqual(f"Bearer {sentinel}", opener.calls[0][0].get_header("Authorization"))
                self.assertEqual(1, response.close_count)


if __name__ == "__main__":
    unittest.main()
