"""app_selection.py：response_model 與 response_class 選用時機範本（原則 IV）。

執行：python app_selection.py（與 envelope.py、app_response_class.py 置於同一目錄）
服務：uvicorn app_selection:app --port 8000
相依：pip install "fastapi==0.141.1" httpx2 uvicorn
"""
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Path, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app_response_class import EnvelopeJSONResponse
from envelope import ERROR_RESPONSES, SuccessResponse, ok, register_exception_handlers


class TaskOut(BaseModel):
    task_id: int
    name: str
    status: Literal["pending", "running", "done"]
    priority: int


class TaskPage(BaseModel):
    """列表資料以物件包覆（原則 I）。"""

    items: list[TaskOut]
    total: int


TASKS: dict[int, dict[str, Any]] = {
    1: {"task_id": 1, "name": "resize-images", "status": "running", "priority": 3,
        "worker_token": "tkn-7f3a", "log": "resized 120/300 images"},
    2: {"task_id": 2, "name": "encode-video", "status": "pending", "priority": 2,
        "worker_token": "tkn-0002", "log": "waiting for worker"},
}

app = FastAPI(title="response selection template")
register_exception_handlers(app)


def find_task(task_id: int) -> dict[str, Any]:
    record = TASKS.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return record


# 情境 A（預設）：JSON 資料回應 → 僅 response_model，由 Pydantic 直接序列化
@app.get("/tasks/{task_id}", response_model=SuccessResponse[TaskOut], status_code=200, responses=ERROR_RESPONSES)
def get_task(task_id: Annotated[int, Path(ge=1)], response: Response) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"  # 以注入之 Response 設定標頭，保留輸出驗證
    return ok(find_task(task_id))


# 情境 B：本體非 JSON → 僅 response_class，並設定 response_model=None
@app.get("/tasks/{task_id}/log", response_class=PlainTextResponse, response_model=None, status_code=200)
def get_task_log(task_id: Annotated[int, Path(ge=1)]) -> str:
    return find_task(task_id)["log"]  # 找不到時仍輸出 JSON 錯誤信封


# 情境 C：需驗證過濾，且由傳輸層統一包裝 → 兩者併用，並以 responses 宣告 200 文件
@app.get(
    "/tasks",
    response_model=TaskPage,  # 內層資料模型；不得宣告 SuccessResponse[TaskPage]
    response_class=EnvelopeJSONResponse,
    status_code=200,
    responses={200: {"model": SuccessResponse[TaskPage], "description": "OK"}, **ERROR_RESPONSES},
)
def list_tasks() -> dict[str, Any]:
    records = list(TASKS.values())  # 含 worker_token、log，由 response_model 移除
    return {"items": records, "total": len(records)}


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for url in ("/tasks/1", "/tasks/1/log", "/tasks", "/tasks/9/log"):
        response = client.get(url)
        print(response.status_code, response.headers["content-type"], response.text)
    print(client.get("/tasks/1").headers["cache-control"])

# 預期輸出：
# 200 application/json {"success":true,"code":200,"message":"OK","data":{"task_id":1,"name":"resize-images","status":"running","priority":3}}
# 200 text/plain; charset=utf-8 resized 120/300 images
# 200 application/json {"success":true,"code":200,"message":"OK","data":{"items":[{"task_id":1,"name":"resize-images","status":"running","priority":3},{"task_id":2,"name":"encode-video","status":"pending","priority":2}],"total":2}}
# 404 application/json {"success":false,"code":404,"message":"Task 9 not found","errors":[{"field":null,"type":"http_error","message":"Task 9 not found"}]}
# no-store
