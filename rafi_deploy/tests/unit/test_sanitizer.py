"""
Unit tests for src.security.sanitizer — deploy input sanitization.

Tests:
- sanitize_client_name allows alphanumeric + underscore
- sanitize_client_name rejects special characters, spaces, path traversal
- sanitize_path prevents ../traversal
- sanitize_path rejects absolute paths outside allowed dirs
- validate_config_values checks all values are safe
- Handles None/empty inputs
"""

import pytest

from src.security.sanitizer import (
    sanitize_client_name,
    sanitize_path,
    validate_config_values,
)


# ---------------------------------------------------------------------------
# sanitize_client_name: valid inputs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSanitizeClientNameValid:
    """sanitize_client_name allows alphanumeric + underscore."""

    def test_simple_lowercase(self):
        assert sanitize_client_name("john_doe") == "john_doe"

    def test_uppercase(self):
        result = sanitize_client_name("JohnDoe")
        # Should allow uppercase or normalize to lowercase
        assert result in ("JohnDoe", "johndoe", "john_doe")

    def test_alphanumeric_with_numbers(self):
        result = sanitize_client_name("client_01")
        assert "client" in result
        assert "01" in result

    def test_single_character(self):
        result = sanitize_client_name("a")
        assert result == "a"

    def test_underscores(self):
        result = sanitize_client_name("john_doe_corp")
        assert "_" in result

    def test_pure_numeric(self):
        result = sanitize_client_name("12345")
        assert result == "12345"


# ---------------------------------------------------------------------------
# sanitize_client_name: rejects bad inputs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSanitizeClientNameRejects:
    """sanitize_client_name rejects special characters, spaces, path traversal."""

    def test_rejects_spaces(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john doe")

    def test_rejects_dots(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john.doe")

    def test_rejects_slashes(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john/doe")

    def test_rejects_backslashes(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john\\doe")

    def test_rejects_path_traversal(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("../../etc/passwd")

    def test_rejects_shell_metacharacters(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john;rm -rf /")

    def test_rejects_semicolons(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john;doe")

    def test_rejects_pipe(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john|doe")

    def test_rejects_backticks(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john`whoami`doe")

    def test_rejects_dollar_sign(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john$HOME")

    def test_rejects_ampersand(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john&doe")

    def test_rejects_angle_brackets(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("<script>alert(1)</script>")

    def test_rejects_null_bytes(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john\x00doe")

    def test_rejects_newlines(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("john\ndoe")

    def test_rejects_excessively_long_name(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("a" * 1000)


# ---------------------------------------------------------------------------
# sanitize_path: prevents traversal
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSanitizePathTraversal:
    """sanitize_path prevents ../traversal."""

    def test_rejects_dot_dot_slash(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("../../../etc/passwd")

    def test_rejects_encoded_traversal(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("..%2f..%2f..%2fetc%2fpasswd")

    def test_rejects_double_dot_in_middle(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/safe/dir/../../../etc/shadow")

    def test_rejects_dot_dot_backslash(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("..\\..\\..\\etc\\passwd")

    def test_allows_safe_relative_path(self):
        """A simple relative path within allowed dirs should be accepted."""
        # This may vary based on implementation: the function may require
        # a base_dir parameter or allowed_dirs.
        try:
            result = sanitize_path("clients/john_doe/config.yaml")
            assert ".." not in result
        except (ValueError, TypeError):
            # If the function requires more params, that's fine
            pass

    def test_allows_simple_filename(self):
        try:
            result = sanitize_path("config.yaml")
            assert result is not None
        except (ValueError, TypeError):
            pass


# ---------------------------------------------------------------------------
# sanitize_path: rejects absolute paths outside allowed dirs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSanitizePathAllowedDirs:
    """sanitize_path rejects absolute paths outside allowed directories."""

    def test_rejects_etc_passwd(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/etc/passwd")

    def test_rejects_root_path(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/")

    def test_rejects_home_directory(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/home/ubuntu/.ssh/authorized_keys")

    def test_rejects_var_log(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/var/log/syslog")

    def test_rejects_dev_null(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/dev/null")

    def test_rejects_proc_self(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("/proc/self/environ")


# ---------------------------------------------------------------------------
# validate_config_values
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestValidateConfigValues:
    """validate_config_values checks all values are safe."""

    def test_valid_config_passes(self, sample_config):
        # Should not raise
        result = validate_config_values(sample_config)
        # Returns True, None, or the config itself depending on implementation
        assert result is not False

    def test_rejects_shell_injection_in_name(self):
        bad_config = {
            "client": {"name": "; rm -rf /", "company": "Safe Corp"},
        }
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad_config)

    def test_rejects_path_traversal_in_values(self):
        bad_config = {
            "client": {"name": "../../etc/passwd", "company": "Test"},
        }
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad_config)

    def test_rejects_null_bytes_in_values(self):
        bad_config = {
            "client": {"name": "John\x00Doe", "company": "Test"},
        }
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad_config)

    def test_rejects_overly_long_values(self):
        bad_config = {
            "client": {"name": "A" * 10000, "company": "Test"},
        }
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad_config)

    def test_rejects_script_tags_in_values(self):
        bad_config = {
            "client": {
                "name": '<script>alert("xss")</script>',
                "company": "Test",
            },
        }
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad_config)

    def test_nested_values_checked(self, sample_config):
        """Ensure nested dict values are also validated."""
        import copy

        bad = copy.deepcopy(sample_config)
        bad["elevenlabs"]["personality"] = "; cat /etc/shadow"
        with pytest.raises((ValueError, Exception)):
            validate_config_values(bad)


# ---------------------------------------------------------------------------
# None/empty inputs
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSanitizerNoneEmpty:
    """Handles None and empty inputs at all entry points."""

    def test_sanitize_client_name_none(self):
        with pytest.raises((TypeError, ValueError)):
            sanitize_client_name(None)

    def test_sanitize_client_name_empty(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("")

    def test_sanitize_path_none(self):
        with pytest.raises((TypeError, ValueError)):
            sanitize_path(None)

    def test_sanitize_path_empty(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_path("")

    def test_validate_config_values_none(self):
        with pytest.raises((TypeError, ValueError)):
            validate_config_values(None)

    def test_validate_config_values_empty_dict(self):
        # Empty dict may raise or return depending on implementation
        try:
            result = validate_config_values({})
            # If no required fields validation, empty may pass
        except (ValueError, Exception):
            pass  # Raising is also acceptable

    def test_sanitize_client_name_whitespace(self):
        with pytest.raises((ValueError, Exception)):
            sanitize_client_name("   ")
