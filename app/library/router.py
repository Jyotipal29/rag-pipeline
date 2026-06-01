"""Research library routes."""

from fastapi import APIRouter

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/")
async def list_papers(
    q: str | None = None,
    topics: str | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    sort: str = "year_desc",
    skip: int = 0,
    limit: int = 20,
):
    """List research papers with search and filtering."""
    # TODO: Implement paper search with MongoDB text search
    # For MVP, return empty list - papers can be seeded later
    return {
        "papers": [],
        "total": 0,
        "has_more": False,
    }


@router.get("/topics")
async def list_topics():
    """List all unique topic tags."""
    # TODO: Implement topic aggregation from research_papers collection
    return {"topics": []}


@router.get("/{paper_id}")
async def get_paper(paper_id: str):
    """Get paper details."""
    # TODO: Implement paper fetch by ID
    return {"error": "Not implemented"}
