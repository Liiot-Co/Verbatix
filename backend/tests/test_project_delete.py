import uuid

from app.routers.projects import delete_project


class FakeResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar(self):
        return self._scalar


class FakeSession:
    def __init__(self, project_id):
        self.project_id = project_id
        self.statements = []
        self.committed = False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.statements.append(sql)
        if sql.startswith("delete from studies"):
            return FakeResult(self.project_id)
        return FakeResult()

    def commit(self):
        self.committed = True


def test_delete_project_removes_round_tree_before_questions_cascade(monkeypatch):
    project_id = uuid.uuid4()
    db = FakeSession(project_id)
    monkeypatch.setattr("app.routers.projects.require_capability", lambda *args: None)

    delete_project(project_id, db=db, user={"id": uuid.uuid4()})

    assert db.statements[0].startswith("delete from rounds")
    assert db.statements[1].startswith("delete from studies")
    assert db.committed is True
