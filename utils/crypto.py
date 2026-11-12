import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from config import ENCRYPTION_KEY


def encrypt(plaintext: str) -> str:
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_CBC)
    ct = cipher.encrypt(pad(plaintext.encode(), AES.block_size))
    return base64.b64encode(cipher.iv + ct).decode()


def decrypt(ciphertext: str) -> str:
    raw = base64.b64decode(ciphertext)
    iv, ct = raw[:16], raw[16:]
    cipher = AES.new(ENCRYPTION_KEY, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ct), AES.block_size).decode()
