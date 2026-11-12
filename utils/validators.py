import re


def is_valid_phone(phone: str) -> bool:
    return bool(re.match(r"^\+\d{7,15}$", phone.strip()))


def parse_live_link(text: str) -> dict | None:
    """
    Returns dict with keys: type ('public'/'invite'), username, msg_id, hash
    Accepts full text messages containing a link, e.g.:
      "Hey! Join our live stream: https://t.me/+IM3CypkvPakyMjk1"
    Also accepts plain links/usernames:
      https://t.me/username/123
      https://t.me/+XXXX  (private invite)
      t.me/username/123
      @username
      username  (plain, min 5 chars)
    """
    text = text.strip()

    # Private invite link (search anywhere in text)
    m = re.search(r"(?:https?://)?t\.me/\+([A-Za-z0-9_-]+)", text)
    if m:
        return {"type": "invite", "hash": m.group(1)}

    # Public channel link with message id (search anywhere in text)
    m = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)/(\d+)", text)
    if m:
        return {"type": "public", "username": m.group(1), "msg_id": int(m.group(2))}

    # t.me/username (no message id) (search anywhere in text)
    m = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", text)
    if m:
        return {"type": "public", "username": m.group(1), "msg_id": None}

    # @username format (search anywhere in text)
    m = re.search(r"@([A-Za-z0-9_]{3,})", text)
    if m:
        return {"type": "public", "username": m.group(1), "msg_id": None}

    # Plain username only (exact match — min 5 chars, starts with letter)
    m = re.match(r"^([A-Za-z][A-Za-z0-9_]{4,})$", text)
    if m:
        return {"type": "public", "username": m.group(1), "msg_id": None}

    return None
