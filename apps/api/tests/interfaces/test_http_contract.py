import asyncio

from httpx import ASGITransport, AsyncClient
from fastapi import HTTPException

from review_assistant.main import app
from review_assistant.interfaces.http.routes import admin
from review_assistant.interfaces.http.routes.knowledge_points import list_knowledge_points
from review_assistant.interfaces.http.routes.examples import list_examples


def test_business_closure_routes_are_published():
    operations = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }

    required = {
        ("/api/courses", "GET"),
        ("/api/courses", "POST"),
        ("/api/coursewares/preflight", "POST"),
        ("/api/homeworks/preflight", "POST"),
        ("/api/homeworks/{homework_id}/solve", "POST"),
        ("/api/questions/{question_id}/attempts", "POST"),
        ("/api/progress/overall", "GET"),
        ("/api/admin/token-usage/by-purpose", "GET"),
        ("/api/admin/token-usage/budget", "GET"),
    }

    assert required <= operations


def test_budget_dashboard_endpoint_serializes_business_state(monkeypatch):
    async def fake_budget():
        return {
            "today_usage": 850,
            "daily_budget": 1000,
            "percentage": 85.0,
            "within_budget": True,
            "call_count_today": 4,
            "warning": "今日 Token 用量已达预算 85.0% (850/1,000)",
        }

    monkeypatch.setattr(admin, "check_budget", fake_budget)

    async def request():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/admin/token-usage/budget")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["today_usage"] == 850
    assert response.json()["within_budget"] is True


def test_knowledge_point_list_rejects_courseware_outside_current_course():
    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    class RecordingDb:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    async def request():
        db = RecordingDb()
        try:
            await list_knowledge_points(
                courseware_id="courseware-from-another-course",
                course_id="current-course",
                db=db,
            )
        except HTTPException as exc:
            return exc, str(db.statement)
        raise AssertionError("expected a scoped 404")

    error, statement = asyncio.run(request())

    assert error.status_code == 404
    assert "coursewares.course_id" in statement


def test_example_list_rejects_knowledge_point_outside_current_course():
    class EmptyResult:
        def scalar_one_or_none(self):
            return None

    class RecordingDb:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    async def request():
        db = RecordingDb()
        try:
            await list_examples(
                kp_id="kp-from-another-course",
                course_id="current-course",
                db=db,
            )
        except HTTPException as exc:
            return exc, str(db.statement)
        raise AssertionError("expected a scoped 404")

    error, statement = asyncio.run(request())

    assert error.status_code == 404
    assert "coursewares.course_id" in statement
