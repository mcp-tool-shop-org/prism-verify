"""Tests for reasoning stripping (Lock 2)."""

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

    def test_verification_catches_nested_patterns(self):
        """If stripping somehow leaves a tag behind, verification catches it."""
        # This tests the verification path — manually construct a scenario
        # where the main strip misses something
        with pytest.raises(StripVerificationError):
            # Force verification to fail by passing content with a tag
            # that our patterns can't strip (malformed)
            from prism.core.stripping import _verify_strip
            _verify_strip("still has <thinking> in it")

    def test_skip_verification(self):
        """Can disable post-strip verification."""
        content = "clean content"
        result = strip_reasoning(content, verify=False)
        assert result.content == content
