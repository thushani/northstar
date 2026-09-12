import unittest
from unittest.mock import MagicMock

from fastapi import HTTPException

from backend.main import delete_job


class DeleteJobTests(unittest.TestCase):
    def test_deletes_role_and_its_saved_analyses(self):
        database = MagicMock()
        role = object()
        database.get.return_value = role

        result = delete_job(42, db=database)

        self.assertEqual(result, {"deleted": True, "job_id": 42})
        database.query.return_value.filter.return_value.delete.assert_called_once_with(
            synchronize_session=False
        )
        database.delete.assert_called_once_with(role)
        database.commit.assert_called_once()

    def test_unknown_role_returns_not_found(self):
        database = MagicMock()
        database.get.return_value = None

        with self.assertRaises(HTTPException) as raised:
            delete_job(404, db=database)

        self.assertEqual(raised.exception.status_code, 404)
        database.delete.assert_not_called()
        database.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
