import pytest
from unittest.mock import Mock, AsyncMock, patch
from core.validators import (
    validate_bot_token,
    validate_user_id,
    validate_menu_id,
    validate_menu_title,
    validate_button_text,
    validate_action_type,
    validate_action_value,
    validate_url,
    validate_min_length,
    validate_max_length,
)
from core.errors import ValidationError


class TestValidators:
    
    def test_validate_bot_token_valid(self):
        """Test valid bot token"""
        result = validate_bot_token("123456789:ABCdefGHIjklMNOpqrsTUVwxyz")
        assert result == "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
    
    def test_validate_bot_token_empty(self):
        """Test empty bot token raises error"""
        with pytest.raises(ValidationError, match="bot token is required"):
            validate_bot_token("")
    
    def test_validate_bot_token_short(self):
        """Test short bot token raises error"""
        with pytest.raises(ValidationError, match="bot token must be at least"):
            validate_bot_token("short")
    
    def test_validate_user_id_valid(self):
        """Test valid user ID"""
        result = validate_user_id(123456789)
        assert result == 123456789
    
    def test_validate_user_id_string(self):
        """Test string user ID is converted to int"""
        result = validate_user_id("123456789")
        assert result == 123456789
    
    def test_validate_menu_title_valid(self):
        """Test valid menu title"""
        result = validate_menu_title("Main Menu")
        assert result == "Main Menu"
    
    def test_validate_menu_title_empty(self):
        """Test empty menu title raises error"""
        with pytest.raises(ValidationError):
            validate_menu_title("")
    
    def test_validate_button_text_valid(self):
        """Test valid button text"""
        result = validate_button_text("Click Me")
        assert result == "Click Me"
    
    def test_validate_action_type_valid(self):
        """Test valid action type"""
        result = validate_action_type("text")
        assert result.value == "text"
    
    def test_validate_action_type_invalid(self):
        """Test invalid action type raises error"""
        with pytest.raises(ValidationError):
            validate_action_type("invalid_type")
    
    @patch('core.validators.validate_url')
    def test_validate_action_value_with_link(self, mock_validate_url):
        """Test action value validation for link"""
        mock_validate_url.return_value = "https://example.com"
        result = validate_action_value("https://example.com", "link")
        assert result == "https://example.com"
        mock_validate_url.assert_called_once()
    
    @patch('core.validators.validate_text_length')
    def test_validate_action_value_with_text(self, mock_validate_text):
        """Test action value validation for text"""
        mock_validate_text.return_value = "Hello World"
        result = validate_action_value("Hello World", "text")
        assert result == "Hello World"
        mock_validate_text.assert_called_once()
    
    def test_validate_url_valid(self):
        """Test valid URL validation"""
        result = validate_url("https://example.com", "url")
        assert result == "https://example.com"
    
    def test_validate_url_invalid(self):
        """Test invalid URL raises error"""
        with pytest.raises(ValidationError, match="must be a valid URL"):
            validate_url("invalid-url", "url")
    
    def test_validate_min_length_valid(self):
        """Test valid min length"""
        result = validate_min_length("hello", 5, "text")
        assert result == "hello"
    
    def test_validate_min_length_too_short(self):
        """Test too short string raises error"""
        with pytest.raises(ValidationError, match="must be at least"):
            validate_min_length("hi", 5, "text")
    
    def test_validate_max_length_valid(self):
        """Test valid max length"""
        result = validate_max_length("hello", 10, "text")
        assert result == "hello"
    
    def test_validate_max_length_too_long(self):
        """Test too long string raises error"""
        with pytest.raises(ValidationError, match="must not exceed"):
            validate_max_length("a" * 100, 10, "text")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
