from fastapi import APIRouter, Depends, Request





router = APIRouter()




@router.get("/", )
async def get_users(
    request: Request
) -> dict[str, list[dict[str, str]]]:
    """Возвращает список пользователей."""
    svc = request.app.state.container.accounts
    if svc is None:
        raise RuntimeError("Хранилище учёток недоступно: Postgres не подключён")
    return {"users": await svc.list()}