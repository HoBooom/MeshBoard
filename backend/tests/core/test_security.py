import unittest

from app.core.security import hash_password, verify_password


class PasswordSecurityTests(unittest.TestCase):
    def test_hash_and_verify_password(self) -> None:
        password_hash = hash_password("correct-horse-battery-staple")

        self.assertTrue(
            verify_password("correct-horse-battery-staple", password_hash)
        )
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_invalid_hash_fails_closed(self) -> None:
        self.assertFalse(verify_password("password", "not-a-bcrypt-hash"))

    def test_passwords_longer_than_bcrypt_limit_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            hash_password("a" * 73)

        valid_hash = hash_password("a" * 72)
        self.assertFalse(verify_password("a" * 73, valid_hash))


if __name__ == "__main__":
    unittest.main()
