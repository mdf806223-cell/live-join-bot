# 📡 Telegram Live Join Bot

## ⚙️ Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure `config.py`
```python
BOT_TOKEN    = "your_botfather_token"       # @BotFather থেকে নাও
API_ID       = 12345678                     # my.telegram.org থেকে
API_HASH     = "your_api_hash"              # my.telegram.org থেকে
ENCRYPTION_KEY = b"your_32byte_key_here!!!!" # exactly 32 bytes
```

### 3. Run
```bash
python main.py
```

---

## 📁 File Structure
```
live_join_bot/
├── main.py
├── config.py
├── requirements.txt
├── database/
│   ├── db.py
│   └── models.py
├── handlers/
│   ├── start.py
│   ├── add_account.py
│   ├── account_list.py
│   ├── join_live.py
│   ├── hand_raise.py
│   ├── leave_live.py
│   ├── export.py
│   └── import_session.py
└── utils/
    ├── crypto.py
    ├── keyboards.py
    ├── validators.py
    └── telegram_client.py
```

---

## 🔑 Important Notes
- `API_ID` and `API_HASH` → https://my.telegram.org/apps থেকে নাও
- `ENCRYPTION_KEY` must be **exactly 32 bytes**
- VPS-এ 24/7 রান করতে `screen` বা `systemd` ব্যবহার করো
- Hand Raise শুধুমাত্র ম্যানুয়াল — ✋ HAND RAISE বাটন চাপলেই কাজ করবে
