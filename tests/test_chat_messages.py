"""
ChatMessage & ClaudeMessage model tests — comprehensive validation of:
  - ChatMessage validator (content normalization)
  - ClaudeMessage validator (system + content normalization)
  - Pydantic field validation
  - Content block flattening (_flatten_content_blocks)
  - Edge cases: empty, unicode, deeply nested structures
"""
import pytest
from pydantic import ValidationError

from main import ChatMessage, ClaudeMessage, _flatten_content_blocks


# ═══════════════════════════════════════════════════════════════════════════════
#  Unit: _flatten_content_blocks()
# ═══════════════════════════════════════════════════════════════════════════════

class TestFlattenContentBlocks:
    """Comprehensive tests for the _flatten_content_blocks normalization function."""

    # GIVEN a plain string
    def test_flatten_plain_string_unchanged(self):
        # WHEN flattening a plain string
        result = _flatten_content_blocks("Hello, World!")
        # THEN it returns as-is
        assert result == "Hello, World!"

    # GIVEN a list of text blocks (Anthropic-style)
    def test_flatten_text_block_list(self):
        blocks = [
            {"type": "text", "text": "First part"},
            {"type": "text", "text": "Second part"},
        ]
        result = _flatten_content_blocks(blocks)
        assert result == "First part\nSecond part"

    # GIVEN a mixed list with text and non-text blocks
    def test_flatten_mixed_block_types_ignores_non_text(self):
        blocks = [
            {"type": "text", "text": "Hello"},
            {"type": "image_url", "image_url": {"url": "..."}},
            {"type": "text", "text": "World"},
        ]
        result = _flatten_content_blocks(blocks)
        # THEN only text blocks are joined
        assert result == "Hello\nWorld"

    # GIVEN blocks with empty text
    def test_flatten_blocks_with_empty_text(self):
        blocks = [
            {"type": "text", "text": "First"},
            {"type": "text", "text": ""},
            {"type": "text", "text": "Third"},
        ]
        result = _flatten_content_blocks(blocks)
        # THEN empty parts are still included (as empty strings)
        assert result == "First\n\nThird"

    # GIVEN blocks missing the "text" key
    def test_flatten_blocks_missing_text_key(self):
        blocks = [
            {"type": "text"},
            {"type": "text", "text": "Present"},
        ]
        result = _flatten_content_blocks(blocks)
        assert result == "\nPresent"

    # GIVEN a list of plain strings (non-dict)
    def test_flatten_string_list(self):
        strings = ["Hello", "World"]
        result = _flatten_content_blocks(strings)
        assert result == "Hello\nWorld"

    # GIVEN a mixed list of dicts and plain strings
    def test_flatten_mixed_dicts_and_strings(self):
        mixed = [
            {"type": "text", "text": "Structured"},
            "Plain string",
        ]
        result = _flatten_content_blocks(mixed)
        assert result == "Structured\nPlain string"

    # GIVEN an empty list
    def test_flatten_empty_list(self):
        result = _flatten_content_blocks([])
        assert result == ""

    # GIVEN None (edge case)
    def test_flatten_none_returns_none(self):
        result = _flatten_content_blocks(None)
        assert result is None

    # GIVEN a list with Unicode content
    def test_flatten_unicode_content(self):
        blocks = [
            {"type": "text", "text": "Hello 你好 🌍"},
            {"type": "text", "text": "Привет мир"},
        ]
        result = _flatten_content_blocks(blocks)
        assert "你好" in result
        assert "Привет мир" in result

    # GIVEN very deeply nested structure (stress test)
    def test_flatten_single_large_text_block(self):
        large_text = "A" * 10000
        result = _flatten_content_blocks([{"type": "text", "text": large_text}])
        assert result == large_text
        assert len(result) == 10000


# ═══════════════════════════════════════════════════════════════════════════════
#  ChatMessage validator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatMessageValidator:
    """Test ChatMessage field validation and normalization."""

    # GIVEN valid plain-string content
    def test_chat_message_plain_content_valid(self):
        msg = ChatMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

    # GIVEN Anthropic-style content blocks
    def test_chat_message_content_blocks_normalized(self):
        msg = ChatMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "Part A"},
                {"type": "text", "text": "Part B"},
            ]
        )
        assert msg.content == "Part A\nPart B"

    # GIVEN a list with mixed content
    def test_chat_message_mixed_blocks_only_text_extracted(self):
        msg = ChatMessage(
            role="user",
            content=[
                {"type": "text", "text": "Text"},
                {"type": "image_url", "image_url": {"url": "http://..."}},
            ]
        )
        assert msg.content == "Text"

    # GIVEN an empty string content
    def test_chat_message_empty_string_valid(self):
        msg = ChatMessage(role="user", content="")
        assert msg.content == ""

    # GIVEN role and content are required
    def test_chat_message_missing_role_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatMessage(content="Hello")
        assert "role" in str(exc_info.value)

    # GIVEN role and content are required
    def test_chat_message_missing_content_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatMessage(role="user")
        assert "content" in str(exc_info.value)

    # GIVEN various role values
    @pytest.mark.parametrize("role", ["user", "assistant", "system", "function"])
    def test_chat_message_various_roles(self, role):
        msg = ChatMessage(role=role, content="test")
        assert msg.role == role

    # GIVEN Unicode content
    def test_chat_message_unicode_content(self):
        msg = ChatMessage(role="user", content="مرحبا بالعالم 🌎")
        assert "مرحبا" in msg.content

    # GIVEN very long content
    def test_chat_message_long_content(self):
        long_text = "X" * 100000
        msg = ChatMessage(role="user", content=long_text)
        assert len(msg.content) == 100000


# ═══════════════════════════════════════════════════════════════════════════════
#  ClaudeMessage validator tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeMessageValidator:
    """Test ClaudeMessage field validation and system normalization."""

    # GIVEN plain-string content
    def test_claude_message_plain_content(self):
        msg = ClaudeMessage(role="user", content="Hello Claude")
        assert msg.content == "Hello Claude"

    # GIVEN Anthropic-style content blocks
    def test_claude_message_blocks_normalized(self):
        msg = ClaudeMessage(
            role="assistant",
            content=[
                {"type": "text", "text": "Alpha"},
                {"type": "text", "text": "Beta"},
            ]
        )
        assert msg.content == "Alpha\nBeta"

    # GIVEN system role
    def test_claude_message_system_role(self):
        msg = ClaudeMessage(role="system", content="System prompt")
        assert msg.role == "system"

    # GIVEN role is required
    def test_claude_message_missing_role_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ClaudeMessage(content="test")
        assert "role" in str(exc_info.value)

    # GIVEN content is required
    def test_claude_message_missing_content_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ClaudeMessage(role="user")
        assert "content" in str(exc_info.value)


# ═══════════════════════════════════════════════════════════════════════════════
#  Integration: ChatMessage in ChatRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestChatMessageIntegration:
    """Test ChatMessage normalization within ChatRequest context."""

    # GIVEN ChatRequest with mixed message formats
    def test_chat_request_messages_normalized(self):
        from main import ChatRequest
        req = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(
                    role="user",
                    content=[
                        {"type": "text", "text": "Part 1"},
                        {"type": "text", "text": "Part 2"},
                    ]
                ),
                ChatMessage(role="assistant", content="Response"),
            ]
        )
        assert req.messages[0].content == "Part 1\nPart 2"
        assert req.messages[1].content == "Response"

    # GIVEN ChatRequest with empty messages
    def test_chat_request_empty_messages_valid(self):
        from main import ChatRequest
        req = ChatRequest(model="gpt-4", messages=[])
        assert req.messages == []

    # GIVEN model defaults to gpt-4
    def test_chat_request_default_model(self):
        from main import ChatRequest
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="Hi")]
        )
        assert req.model == "gpt-4"

    # GIVEN stream defaults to False
    def test_chat_request_default_stream(self):
        from main import ChatRequest
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="Hi")]
        )
        assert req.stream is False

    # GIVEN temperature in valid range
    @pytest.mark.parametrize("temp", [0.0, 0.5, 1.0, 2.0])
    def test_chat_request_temperature_valid_range(self, temp):
        from main import ChatRequest
        req = ChatRequest(
            messages=[ChatMessage(role="user", content="Hi")],
            temperature=temp
        )
        assert req.temperature == temp


# ═══════════════════════════════════════════════════════════════════════════════
#  Integration: ClaudeMessage in ClaudeRequest
# ═══════════════════════════════════════════════════════════════════════════════

class TestClaudeMessageIntegration:
    """Test ClaudeMessage normalization within ClaudeRequest context."""

    # GIVEN ClaudeRequest with system prompt
    def test_claude_request_with_system(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            model="claude-3-opus",
            messages=[
                ClaudeMessage(role="user", content="Test")
            ],
            system="You are helpful."
        )
        assert req.system == "You are helpful."

    # GIVEN system is optional
    def test_claude_request_system_optional(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            model="claude-3-opus",
            messages=[
                ClaudeMessage(role="user", content="Test")
            ]
        )
        assert req.system is None

    # GIVEN system can be a list (normalized to string)
    def test_claude_request_system_list_normalized(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            model="claude-3-opus",
            messages=[
                ClaudeMessage(role="user", content="Test")
            ],
            system=[
                {"type": "text", "text": "System"},
                {"type": "text", "text": "Prompt"},
            ]
        )
        assert req.system == "System\nPrompt"

    # GIVEN max_tokens has min/max constraints
    def test_claude_request_max_tokens_in_range(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            model="claude-3-opus",
            messages=[ClaudeMessage(role="user", content="Test")],
            max_tokens=8000
        )
        assert req.max_tokens == 8000

    # GIVEN max_tokens below minimum (ge=1)
    def test_claude_request_max_tokens_below_min_raises(self):
        from main import ClaudeRequest
        with pytest.raises(ValidationError) as exc_info:
            ClaudeRequest(
                model="claude-3-opus",
                messages=[ClaudeMessage(role="user", content="Test")],
                max_tokens=0
            )
        assert "max_tokens" in str(exc_info.value)

    # GIVEN max_tokens above maximum (le=200000)
    def test_claude_request_max_tokens_above_max_raises(self):
        from main import ClaudeRequest
        with pytest.raises(ValidationError) as exc_info:
            ClaudeRequest(
                model="claude-3-opus",
                messages=[ClaudeMessage(role="user", content="Test")],
                max_tokens=250000
            )
        assert "max_tokens" in str(exc_info.value)

    # GIVEN temperature has min/max constraints
    def test_claude_request_temperature_in_range(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            model="claude-3-opus",
            messages=[ClaudeMessage(role="user", content="Test")],
            temperature=1.5
        )
        assert req.temperature == 1.5

    # GIVEN temperature below minimum (ge=0.0)
    def test_claude_request_temperature_below_min_raises(self):
        from main import ClaudeRequest
        with pytest.raises(ValidationError) as exc_info:
            ClaudeRequest(
                model="claude-3-opus",
                messages=[ClaudeMessage(role="user", content="Test")],
                temperature=-0.5
            )
        assert "temperature" in str(exc_info.value)

    # GIVEN temperature above maximum (le=2.0)
    def test_claude_request_temperature_above_max_raises(self):
        from main import ClaudeRequest
        with pytest.raises(ValidationError) as exc_info:
            ClaudeRequest(
                model="claude-3-opus",
                messages=[ClaudeMessage(role="user", content="Test")],
                temperature=2.5
            )
        assert "temperature" in str(exc_info.value)

    # GIVEN model defaults to gpt-4
    def test_claude_request_default_model(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            messages=[ClaudeMessage(role="user", content="Test")]
        )
        assert req.model == "gpt-4"

    # GIVEN stream defaults to False
    def test_claude_request_default_stream(self):
        from main import ClaudeRequest
        req = ClaudeRequest(
            messages=[ClaudeMessage(role="user", content="Test")]
        )
        assert req.stream is False
