from datetime import timedelta
from services.common.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_and_verify():
    password = "SuperSecretPassword#123"
    hashed = hash_password(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword", hashed) is False


def test_jwt_token_flow():
    payload_data = {"sub": "user-uuid-1234", "role": "admin"}
    token = create_access_token(payload_data, expires_delta=timedelta(minutes=10))

    decoded = decode_access_token(token)
    assert decoded is not None
    assert decoded["sub"] == "user-uuid-1234"
    assert decoded["role"] == "admin"


def test_jwt_invalid_token():
    assert decode_access_token("invalid.token.structure") is None
