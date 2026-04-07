"""Tests for the tool registry module."""
import pytest

from tools.registry import (
    parse_tool_call,
    _extract_balanced_json,
    default_manifest,
)


class TestParseToolCall:
    """Tests for parse_tool_call — the critical LLM output parser."""

    def test_direct_json(self):
        text = '{"tool": "nmap_scan", "args": {"target": "10.0.0.1"}}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "nmap_scan"
        assert result["args"]["target"] == "10.0.0.1"

    def test_empty_string(self):
        assert parse_tool_call("") is None

    def test_whitespace_only(self):
        assert parse_tool_call("   \n  ") is None

    def test_plain_text(self):
        assert parse_tool_call("I'll scan the target now.") is None

    def test_json_with_no_tool_key(self):
        assert parse_tool_call('{"action": "scan", "target": "10.0.0.1"}') is None

    def test_tool_call_marker(self):
        text = 'TOOL_CALL: {"tool": "shell_exec", "args": {"command": "whoami"}}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "shell_exec"
        assert result["args"]["command"] == "whoami"

    def test_fenced_code_block(self):
        text = '```json\n{"tool": "file_read", "args": {"path": "/etc/hosts"}}\n```'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "file_read"

    def test_embedded_json_in_prose_rejected(self):
        """JSON buried in the middle of narrative text should be rejected."""
        text = (
            "I will now perform a scan of the target system to identify open ports "
            "and running services. Let me use nmap for this purpose. "
            '{"tool": "nmap_scan", "args": {"target": "10.0.0.1"}} '
            "Once I get the output from the scan I will analyze the results "
            "and identify potential vulnerabilities in the running services."
        )
        assert parse_tool_call(text) is None

    def test_json_at_start_with_trailing_text(self):
        """JSON at the start with minor trailing text should still be extracted."""
        text = '{"tool": "shell_exec", "args": {"command": "id"}} done'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "shell_exec"

    def test_missing_args_defaults_to_empty(self):
        text = '{"tool": "system_status"}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "system_status"
        assert result["args"] == {}

    def test_concatenated_json_objects(self):
        """When LLM outputs multiple JSON objects, only the first is parsed."""
        text = '{"tool": "shell_exec", "args": {"command": "id"}}{"tool": "file_read", "args": {"path": "/etc/passwd"}}'
        result = parse_tool_call(text)
        assert result is not None
        assert result["tool"] == "shell_exec"


class TestExtractBalancedJson:
    """Tests for the balanced JSON extraction helper."""

    def test_simple_object(self):
        text = '{"key": "value"}'
        assert _extract_balanced_json(text, 0) == '{"key": "value"}'

    def test_nested_braces(self):
        text = '{"tool": "x", "args": {"a": {"b": 1}}}'
        assert _extract_balanced_json(text, 0) == text

    def test_string_with_braces(self):
        text = '{"cmd": "echo {hello}"}'
        assert _extract_balanced_json(text, 0) == text

    def test_start_not_brace(self):
        assert _extract_balanced_json("abc", 0) is None

    def test_start_out_of_range(self):
        assert _extract_balanced_json("abc", 10) is None

    def test_unbalanced(self):
        assert _extract_balanced_json('{"key": "value"', 0) is None


class TestDefaultManifest:
    """Tests for default_manifest."""

    def test_returns_expected_keys(self):
        m = default_manifest("test_tool", "A test tool")
        assert m["name"] == "test_tool"
        assert m["description"] == "A test tool"
        assert m["action_class"] == "read_only"
        assert m["trust_tier"] == "tier_1"
        assert m["provider_affinity"] == "any"
        assert m["capabilities"] == []

    def test_empty_description(self):
        m = default_manifest("x")
        assert m["description"] == ""
