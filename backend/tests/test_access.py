"""visible_project_ids() is the single source of role-based visibility (sección 2.1):
admin sees everything unfiltered, non-admin sees only projects they're assigned to."""
import uuid

from app.core.access import visible_project_ids

USER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


class FakeResult:
    def __init__(self, scalar=None, scalars_list=None):
        self._scalar = scalar
        self._scalars_list = scalars_list or []

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._scalars_list


class FakeSession:
    def __init__(self, is_admin_result, assigned_project_ids):
        self._is_admin_result = is_admin_result
        self._assigned_project_ids = assigned_project_ids

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "from user_roles" in sql:
            return FakeResult(scalar=self._is_admin_result)
        if "from assignments" in sql:
            return FakeResult(scalars_list=self._assigned_project_ids)
        raise AssertionError(f"unexpected query: {sql}")


def test_admin_sees_everything_unfiltered():
    db = FakeSession(is_admin_result=1, assigned_project_ids=[])
    assert visible_project_ids(db, USER_ID) is None


def test_codificador_with_assignment_sees_only_that_project():
    db = FakeSession(is_admin_result=None, assigned_project_ids=[PROJECT_ID])
    assert visible_project_ids(db, USER_ID) == [PROJECT_ID]


def test_codificador_without_assignments_sees_nothing():
    db = FakeSession(is_admin_result=None, assigned_project_ids=[])
    assert visible_project_ids(db, USER_ID) == []
