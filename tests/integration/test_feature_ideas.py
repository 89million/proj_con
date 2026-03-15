"""Tests for the feature ideas board."""

from sqlalchemy import select

from app.models import FeatureIdea, IdeaUpvote

from .conftest import make_client


async def test_ideas_page_accessible(engine, db, test_user):
    """GET /ideas returns 200 for logged-in users."""
    async with make_client(engine, test_user) as client:
        resp = await client.get("/ideas")

    assert resp.status_code == 200
    assert "Feature Ideas" in resp.text


async def test_submit_idea_creates_record(engine, db, test_user, monkeypatch):
    """POST /ideas creates a new idea with Gemini complexity estimate."""

    class FakeResult:
        text = "Moderate — new route and template needed"

    class FakeModels:
        def generate_content(self, **kwargs):
            return FakeResult()

    class FakeClient:
        def __init__(self, **kwargs):
            self.models = FakeModels()

    monkeypatch.setattr("app.main.settings.gemini_api_key", "fake-key")

    import google.genai

    monkeypatch.setattr(google.genai, "Client", FakeClient)

    async with make_client(engine, test_user) as client:
        resp = await client.post(
            "/ideas",
            data={"title": "Dark Mode", "description": "Add a dark theme option"},
        )

    assert resp.status_code == 302

    result = await db.execute(select(FeatureIdea).where(FeatureIdea.title == "Dark Mode"))
    idea = result.scalar_one()
    assert idea.description == "Add a dark theme option"
    assert idea.complexity.startswith("Moderate")
    assert idea.author_id == test_user.id


async def test_submit_idea_cap_at_3(engine, db, test_user, monkeypatch):
    """Users cannot submit more than 3 ideas."""
    monkeypatch.setattr("app.main.settings.gemini_api_key", "")

    async with make_client(engine, test_user) as client:
        for i in range(3):
            await client.post(
                "/ideas",
                data={"title": f"Idea {i}", "description": f"Description {i}"},
            )

        # 4th should be blocked
        resp = await client.post(
            "/ideas",
            data={"title": "Idea 3", "description": "Description 3"},
        )

    assert resp.status_code == 302
    result = await db.execute(select(FeatureIdea).where(FeatureIdea.author_id == test_user.id))
    assert len(result.scalars().all()) == 3


async def test_upvote_toggle(engine, db, test_user, test_admin, monkeypatch):
    """First upvote adds, second removes."""
    from app import crud

    idea = await crud.create_idea(db, test_admin.id, "Test", "Test idea", None)

    async with make_client(engine, test_user) as client:
        # Upvote
        resp = await client.post(f"/ideas/{idea.id}/upvote")
        assert resp.status_code == 302

    result = await db.execute(
        select(IdeaUpvote).where(IdeaUpvote.idea_id == idea.id, IdeaUpvote.user_id == test_user.id)
    )
    assert result.scalar_one_or_none() is not None

    # Remove upvote
    async with make_client(engine, test_user) as client:
        resp = await client.post(f"/ideas/{idea.id}/upvote")

    result = await db.execute(
        select(IdeaUpvote).where(IdeaUpvote.idea_id == idea.id, IdeaUpvote.user_id == test_user.id)
    )
    assert result.scalar_one_or_none() is None


async def test_ideas_sorted_by_upvotes(engine, db, test_user, test_admin, extra_user):
    """Most upvoted ideas appear first."""
    from app import crud

    await crud.create_idea(db, test_admin.id, "Less Popular", "Desc", None)
    idea_b = await crud.create_idea(db, test_admin.id, "More Popular", "Desc", None)

    # Give idea_b 2 upvotes, idea_a 0
    await crud.toggle_upvote(db, idea_b.id, test_user.id)
    await crud.toggle_upvote(db, idea_b.id, extra_user.id)

    async with make_client(engine, test_user) as client:
        resp = await client.get("/ideas")

    assert resp.status_code == 200
    assert resp.text.index("More Popular") < resp.text.index("Less Popular")


async def test_admin_delete_idea(engine, db, test_admin, test_user):
    """Admin can delete ideas."""
    from app import crud

    idea = await crud.create_idea(db, test_user.id, "Bad Idea", "Desc", None)

    async with make_client(engine, test_admin) as client:
        resp = await client.post(f"/ideas/{idea.id}/delete")

    assert resp.status_code == 302

    result = await db.execute(select(FeatureIdea).where(FeatureIdea.id == idea.id))
    assert result.scalar_one_or_none() is None


async def test_complexity_displayed(engine, db, test_admin, test_user):
    """Gemini complexity estimate is shown on the page."""
    from app import crud

    await crud.create_idea(
        db,
        test_admin.id,
        "Easy Feature",
        "Simple thing",
        "Quick Win — just add a CSS class to the template",
    )

    async with make_client(engine, test_user) as client:
        resp = await client.get("/ideas")

    assert "Quick Win" in resp.text
    assert "just add a CSS class" in resp.text


async def test_idea_xss_escaped_on_render(engine, db, test_user, monkeypatch):
    """Jinja2 auto-escaping prevents XSS when rendering ideas."""
    monkeypatch.setattr("app.main.settings.gemini_api_key", "")

    async with make_client(engine, test_user) as client:
        await client.post(
            "/ideas",
            data={
                "title": '<script>alert("xss")</script>',
                "description": '<img src=x onerror="alert(1)">',
            },
        )
        # Verify rendering is safe
        resp = await client.get("/ideas")

    assert resp.status_code == 200
    assert '<script>alert("xss")</script>' not in resp.text
    assert "&lt;script&gt;" in resp.text
    assert 'onerror="alert(1)"' not in resp.text
