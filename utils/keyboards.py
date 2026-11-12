from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📡 Join Live",    callback_data="join_live"),
            InlineKeyboardButton(text="✋ Hand Raise",   callback_data="hand_raise"),
        ],
        [
            InlineKeyboardButton(text="➕ Add Account",  callback_data="add_account"),
            InlineKeyboardButton(text="📋 Account List", callback_data="account_list"),
        ],
        [
            InlineKeyboardButton(text="🚪 Leave Live",   callback_data="leave_live"),
        ],
    ])


def cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="cancel")]
    ])


def account_card_keyboard(account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Rename",       callback_data=f"rename_{account_id}"),
            InlineKeyboardButton(text="🗑️ Logout",        callback_data=f"logout_{account_id}"),
        ],
        [
            InlineKeyboardButton(text="🏠 Back to Menu",  callback_data="home"),
        ],
    ])


def back_home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Back to Menu", callback_data="home")]
    ])


def confirm_keyboard(action: str, account_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes", callback_data=f"confirm_{action}_{account_id}"),
            InlineKeyboardButton(text="❌ No",  callback_data=f"account_detail_{account_id}"),
        ]
    ])
