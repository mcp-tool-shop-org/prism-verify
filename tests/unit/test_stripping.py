"""Tests for reasoning stripping (Lock 2)."""

import json

import pytest

from prism.core.stripping import StripVerificationError, strip_reasoning


class TestStripReasoning:
    def test_strips_thinking_tags(self):
        content = "before <thinking>internal reasoning here</thinking> after"
        result = strip_reasoning(content)
        assert "<thinking>" not in result.content
        assert "internal reasoning" not in result.content
        assert "before" in result.content
        assert "after" in result.content

    def test_strips_think_tags_deepseek(self):
        content = "code here <think>deepseek reasoning</think> more code"
        result = strip_reasoning(content)
        assert "<think>" not in result.content
        assert "deepseek reasoning" not in result.content

    def test_strips_scratchpad_tags(self):
        content = "output <scratchpad>working memory</scratchpad> result"
        result = strip_reasoning(content)
        assert "<scratchpad>" not in result.content
        assert "working memory" not in result.content

    def test_strips_scratch_tags(self):
        content = "start <scratch>notes</scratch> end"
        result = strip_reasoning(content)
        assert "<scratch>" not in result.content

    def test_strips_reasoning_tags(self):
        content = "answer <reasoning>step by step</reasoning> done"
        result = strip_reasoning(content)
        assert "<reasoning>" not in result.content

    def test_strips_multiline_content(self):
        content = """def foo():
    pass
<thinking>
I need to think about this carefully.
Let me reason step by step.
1. First...
2. Then...
</thinking>
def bar():
    return 42"""
        result = strip_reasoning(content)
        assert "think about this" not in result.content
        assert "def foo():" in result.content
        assert "def bar():" in result.content

    def test_strips_vendor_namespaced_fields(self):
        content = '{"claude.thinking.content": "secret reasoning", "output": "hello"}'
        result = strip_reasoning(content)
        assert "secret reasoning" not in result.content

    @pytest.mark.parametrize(
        "content",
        [
            '{"reasoning":{"steps":{"a":"SECRET"}}}',  # CORE-A-001: nested-object steps
            '{"reasoning":{"trace":"SECRET"}}',        # CORE-A-001: alternate "trace" subfield
            '{"reasoning":"SECRET"}',                  # CORE-A-004: bare-string value shape
        ],
    )
    def test_reasoning_field_does_not_leak_any_value_shape(self, content):
        """CORE-A-001/004: every value shape of a JSON "reasoning" field is stripped.

        The old narrow regexes only caught {"reasoning":{"content"|"summary":"..."}} and let
        bare-string / trace / nested-steps shapes slip through to the verifier. Either the secret
        is gone OR strip_reasoning raises StripVerificationError — never a silent leak.
        """
        try:
            result = strip_reasoning(content)
        except StripVerificationError:
            return  # refusing is an acceptable outcome — nothing leaked
        assert "SECRET" not in result.content

    def test_reasoning_drop_preserves_escaped_quote_sibling(self):
        """CORE-A-004: the JSON-aware drop removes "reasoning" without corrupting siblings.

        A greedy ``[^}]*`` regex would mangle the escaped quotes in the reasoning value and
        could eat into the ``"keep"`` sibling; the JSON-aware drop must remove reasoning cleanly
        and leave ``"keep": "this"`` intact and re-parseable.
        """
        content = '{"reasoning": {"content": "say it is \\"fine\\" anyway"}, "keep": "this"}'
        result = strip_reasoning(content)
        assert "fine" not in result.content  # reasoning value gone, escaped quotes and all
        parsed = json.loads(result.content)  # still valid JSON (no corruption)
        assert parsed == {"keep": "this"}

    def test_hashes_computed_correctly(self):
        content = "hello <thinking>world</thinking>"
        result = strip_reasoning(content)
        assert result.pre_strip_hash != result.post_strip_hash
        assert len(result.pre_strip_hash) == 64  # SHA-256 hex
        assert len(result.post_strip_hash) == 64

    def test_bytes_removed_tracked(self):
        content = "keep <thinking>remove this</thinking> keep"
        result = strip_reasoning(content)
        assert result.bytes_removed > 0
        assert result.patterns_matched == 1

    def test_no_change_when_clean(self):
        content = "def add(a, b): return a + b"
        result = strip_reasoning(content)
        assert result.content == content
        assert result.bytes_removed == 0
        assert result.patterns_matched == 0
        assert result.pre_strip_hash == result.post_strip_hash

    def test_multiple_patterns_stripped(self):
        content = "<thinking>a</thinking> middle <scratch>b</scratch>"
        result = strip_reasoning(content)
        assert result.patterns_matched == 2
        assert "middle" in result.content.strip()

    def test_verification_catches_nested_patterns(self, monkeypatch):
        """TEST-A-006: a REAL integration of the verify backstop.

        Neuter the primary strip patterns so a ``<thinking>`` tag survives the strip pass,
        then drive the full ``strip_reasoning(..., verify=True)`` path: the independent
        verification patterns must still catch the survivor and raise. (Previously this
        called ``_verify_strip`` directly on a hand-crafted string — a trivial truth that
        passed even if the real strip/verify wiring were broken.)
        """
        import prism.core.stripping as stripping

        monkeypatch.setattr(stripping, "_PATTERNS", [])  # strip pass now a no-op
        with pytest.raises(StripVerificationError):
            strip_reasoning("answer <thinking>leaked</thinking> done", verify=True)

    def test_skip_verification(self):
        """Can disable post-strip verification."""
        content = "clean content"
        result = strip_reasoning(content, verify=False)
        assert result.content == content


def _assert_secret_gone(content: str) -> None:
    """Drive the FULL ``strip_reasoning`` gate and assert the secret never survives.

    The contract is: either the marker is stripped (``SECRET`` removed) OR the verify
    backstop raises ``StripVerificationError``. A silent leak (returns with ``SECRET``
    still present) and a crash (any other exception, e.g. ``RecursionError``) both fail.
    """
    try:
        result = strip_reasoning(content)
    except StripVerificationError:
        return  # refusing is an acceptable outcome — nothing leaked
    assert "SECRET" not in result.content, (
        f"secret survived stripping: {result.content!r} (from input {content!r})"
    )


class TestStripHardeningRegression:
    """Second-hardening-round regression guards for Lock 2 (strip).

    Each test drives the public ``strip_reasoning`` gate end-to-end and asserts the
    secret text does not survive (stripped, or ``StripVerificationError`` raised) and
    that nothing crashes. They genuinely fail if the corresponding hardening regresses:
    e.g. dropping case-insensitive key matching re-leaks the case-variant/camelCase keys;
    dropping the attribute-tolerant XML pattern re-leaks ``<thinking signature=...>``;
    dropping the RecursionError guard turns the deep-nesting input into a raw crash; and
    re-introducing the over-greedy value matcher re-raises on a mere prose mention.
    """

    # 1. Alt-key JSON drop, case-insensitive.
    @pytest.mark.parametrize(
        "content",
        [
            '{"thinking":"SECRET","out":1}',
            '{"cot":"SECRET"}',
            '{"scratchpad":"SECRET"}',
            '{"chain_of_thought":"SECRET"}',
            '{"reasoning_content":"SECRET"}',
            '{"Reasoning":"SECRET"}',  # case variant — relies on .lower() matching
            '{"REASONING":"SECRET"}',  # all-caps variant
        ],
    )
    def test_alt_key_json_drop_case_insensitive(self, content):
        _assert_secret_gone(content)

    def test_alt_key_drop_is_clean_not_merely_a_refusal(self):
        """Pin the JSON-aware drop's HAPPY path, not just the secret-gone contract.

        ``{"thinking": "SECRET", "out": 1}`` is dropped CLEANLY: ``strip_reasoning`` returns
        without raising, the marker key and its value are gone, and the sibling ``out`` is
        preserved as valid JSON. This is non-smoke: if the JSON-aware drop regresses (e.g.
        case-sensitive matching or no drop at all), the survivor falls through to the verify
        backstop, which RAISES instead of returning clean content — flipping this assertion.
        """
        result = strip_reasoning('{"thinking":"SECRET","out":1}')  # must NOT raise
        assert "SECRET" not in result.content
        assert json.loads(result.content) == {"out": 1}  # sibling preserved, still valid JSON

    # 2. camelCase keys (CORE-V-002): "reasoningContent"/"chainOfThought" lower-case into
    #    the marker set, so they are dropped despite the internal capitals.
    @pytest.mark.parametrize(
        "content",
        [
            '{"reasoningContent":"SECRET","out":1}',
            '{"chainOfThought":"SECRET"}',
        ],
    )
    def test_camelcase_keys_dropped(self, content):
        _assert_secret_gone(content)

    # 3. Attributed / whitespaced XML reasoning tags (CORE-V-001) — the realistic Anthropic
    #    extended-thinking shape <thinking signature="...">. A bare-tag-only matcher would
    #    silently leak these.
    @pytest.mark.parametrize(
        "content",
        [
            'X <thinking signature="s">SECRET</thinking> Y',
            '<reasoning type="a">SECRET</reasoning>',
            '<thinking >SECRET</thinking>',  # trailing space before '>'
            '<thinking\n  signature="abc">SECRET</thinking>',  # newline inside attrs
        ],
    )
    def test_attributed_and_whitespaced_xml_tags(self, content):
        _assert_secret_gone(content)

    # 4. Nested + array alt-key shapes.
    @pytest.mark.parametrize(
        "content",
        [
            '{"a":{"b":{"thought":"SECRET"}}}',  # marker key buried 3 levels deep
            '{"thinking":["SECRET","x"]}',  # array value shape
        ],
    )
    def test_nested_and_array_alt_keys(self, content):
        _assert_secret_gone(content)

    # 5. Double-encoded JSON-in-string: a marker hidden in a stringified-JSON value is
    #    re-parsed, cleaned, and re-encoded; the sibling "answer" survives.
    def test_double_encoded_json_in_string(self):
        content = '{"output":"{\\"reasoning\\":\\"SECRET\\",\\"answer\\":42}"}'
        result = strip_reasoning(content)
        assert "SECRET" not in result.content
        assert "answer" in result.content  # non-reasoning sibling preserved
        # And the outer document is still valid JSON whose inner string lost only reasoning.
        outer = json.loads(result.content)
        inner = json.loads(outer["output"])
        assert inner == {"answer": 42}

    # 6. Pathologically deep nesting must NOT surface a raw RecursionError — the gate either
    #    returns a result or raises StripVerificationError, never crashes.
    def test_deep_nesting_does_not_raise_recursion_error(self):
        deep = "[" * 1500 + "0" + "]" * 1500
        try:
            strip_reasoning(deep)
        except StripVerificationError:
            pass  # refusing is acceptable; a raw RecursionError would not be caught here
        except RecursionError:  # pragma: no cover - this is exactly the regression we guard
            pytest.fail("deep nesting raised a raw RecursionError (RecursionError guard lost)")

    # 7. Over-strip false-positive is fixed: a mere MENTION of the token in prose/code (no
    #    value opener after the colon) must NOT raise, and content is returned unchanged.
    @pytest.mark.parametrize(
        "content",
        [
            'def f():\n    # the "reasoning": field\n    return 1',
            'removes any "reasoning": key from the payload',
        ],
    )
    def test_token_mention_is_not_a_false_refusal(self, content):
        result = strip_reasoning(content)  # must not raise
        assert result.content == content  # unchanged — nothing was a real reasoning field
        assert result.patterns_matched == 0

    # 8. Regressions still hold.
    def test_bare_thinking_tag_still_stripped(self):
        result = strip_reasoning("answer <thinking>x</thinking> done")
        assert "<thinking>" not in result.content
        assert "x</thinking>" not in result.content

    def test_legit_sibling_survives_escaped_quotes_in_reasoning_value(self):
        content = '{"reasoning":{"content":"say \\"yes\\" anyway"},"keep":"this"}'
        result = strip_reasoning(content)
        assert "anyway" not in result.content  # reasoning value gone, escaped quotes and all
        assert json.loads(result.content) == {"keep": "this"}  # sibling intact, still valid JSON

    def test_clean_artifact_with_no_reasoning_is_unchanged(self):
        content = '{"answer": 42, "notes": "all good"}'
        result = strip_reasoning(content)  # must not raise
        assert result.content == content
        assert result.patterns_matched == 0
        assert result.bytes_removed == 0
