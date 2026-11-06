import pytest
from unittest.mock import AsyncMock, patch
from constructor.handlers import (
    show_user_bots,
    start,
    add_bot_click,
)
from core.permissions import check_user_permission
from telegram import Update
from telegram.ext import CallbackContext


class TestHandlers:
    
    @patch('constructor.handlers.check_user_permission')
    @patch('constructor.handlers.AsyncSessionLocal')
    async def test_show_user_bots_no_permission(self, mock_session, mock_permission):
        """Test showing bots without permission"""
        mock_permission.return_value = False
        mock_session.return_value.__aenter__.return_value.execute.return_value.scalar_one_or_none.return_value = None
        
        update = Mock(spec=Update)
        update.effective_user.id = 123
        update.message.reply_text = AsyncMock()
        
        await show_user_bots(update, Mock(spec=CallbackContext))
        
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "Xizmatga kirish huquqi yo'q" in call_args[0][0]
    
    @patch('constructor.handlers.check_user_permission')
    @patch('constructor.handlers.AsyncSessionLocal')
    async def test_start(self, mock_session, mock_permission):
        """Test start command"""
        mock_permission.return_value = True
        mock_session.return_value.__aenter__.return_value.execute.return_value.scalar_one_or_none.return_value = None
        
        update = Mock(spec=Update)
        update.effective_user.id = 123
        
        await start(update, Mock(spec=CallbackContext))
        
        mock_permission.assert_called_once_with(123)
    
    @patch('constructor.handlers.AsyncSessionLocal')
    @patch('constructor.handlers.check_user_permission')
    async def test_add_bot_click(self, mock_permission, mock_session):
        """Test add bot click"""
        mock_permission.return_value = True
        mock_session.return_value.__aenter__.return_value.execute.return_value.scalar_one_or_none.return_value = None
        
        update = Mock(spec=Update)
        update.callback_query.answer = AsyncMock()
        update.callback_query.message.reply_text = AsyncMock()
        
        await add_bot_click(update, Mock(spec=CallbackContext))
        
        update.callback_query.answer.assert_called_once()
        update.callback_query.message.reply_text.assert_called_once()


class TestPermissions:
    
    @patch('core.permissions.AsyncSessionLocal')
    async def test_check_user_permission_true(self, mock_session):
        """Test permission check returns True"""
        mock_session.return_value.__aenter__.return_value.execute.return_value.scalar_one_or_none.return_value = None
        result = await check_user_permission(123)
        assert result is True
    
    @patch('core.permissions.AsyncSessionLocal')
    async def test_check_user_permission_false(self, mock_session):
        """Test permission check returns False for user without permission"""
        mock_session.return_value.__aenter__.return_value.execute.return_value.scalar_one_or_none.return_value = None
        result = await check_user_permission(999)
        assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
