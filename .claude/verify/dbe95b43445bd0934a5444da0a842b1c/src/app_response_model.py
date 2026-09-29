"""app_response_model.py：response_model 範本（原則 II，套用原則 I 之信封）。

執行：python app_response_model.py（與 envelope.py 置於同一目錄）
服務：uvicorn app_response_model:app --port 8000
相依：pip install "fastapi==0.141.1" httpx2 uvicorn
"""
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Path
from pydantic import BaseModel, Field

from envelope import ERROR_RESPONSES, ApiError, ErrorDetail, SuccessResponse, ok, register_exception_handlers


class TaskOut(BaseModel):
    """對外模型：不含內部欄位 worker_token。"""

    task_id: int
    name: str
    status: Literal["pending", "running", "done"]
    priority: int


class TaskCreate(BaseModel):
    """請求本體模型。"""

    name: str = Field(min_length=1, max_length=50)
    priority: int = Field(default=5, ge=1, le=10)


# 模擬資料儲存：內部紀錄含 worker_token，不得對外輸出
TASKS: dict[int, dict[str, Any]] = {
    1: {"task_id": 1, "name": "resize-images", "status": "running", "priority": 3, "worker_token": "tkn-7f3a"},
}

app = FastAPI(title="response_model template")
register_exception_handlers(app)


@app.get(
    "/tasks/{task_id}",
    response_model=SuccessResponse[TaskOut],  # 契約：成功信封 + 對外模型；不宣告 response_class
    status_code=200,
    responses=ERROR_RESPONSES,  # 文件：錯誤信封（400、4XX、5XX）
)
def get_task(task_id: Annotated[int, Path(ge=1)]) -> dict[str, Any]:
    record = TASKS.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return ok(record)  # record 含 worker_token，由 response_model 移除


@app.post(
    "/tasks",
    response_model=SuccessResponse[TaskOut],
    status_code=200,
    responses=ERROR_RESPONSES,
)
def create_task(payload: TaskCreate) -> dict[str, Any]:
    if any(task["name"] == payload.name for task in TASKS.values()):
        raise ApiError(
            "Task name already exists",
            [ErrorDetail(field="body.name", type="duplicate", message=f"{payload.name} is already queued")],
        )
    task_id = max(TASKS) + 1
    TASKS[task_id] = {
        "task_id": task_id,
        "status": "pending",
        "worker_token": f"tkn-{task_id:04d}",
        **payload.model_dump(),
    }
    return ok(TASKS[task_id], code=200)  # code 與 status_code 相同


@app.get(
    "/tasks/{task_id}/legacy",
    response_model=SuccessResponse[TaskOut],
    status_code=200,
    responses=ERROR_RESPONSES,
)
def get_legacy_task(task_id: Annotated[int, Path(ge=1)]) -> dict[str, Any]:
    # 違反契約之示範：舊資料來源之 status 不在 TaskOut 允許值內
    return ok({"task_id": task_id, "name": "legacy-job", "status": "unknown", "priority": 1})


if __name__ == "__main__":
    from fastapi.exceptions import ResponseValidationError
    from fastapi.testclient import TestClient

    client = TestClient(app, raise_server_exceptions=False)  # 取得 500 回應，不於測試中拋出例外
    cases = [
        ("GET", "/tasks/1", None),  # 200：成功信封，worker_token 已移除
        ("GET", "/tasks/0", None),  # 400：路徑參數驗證失敗（取代預設 422）
        ("GET", "/tasks/9", None),  # 404：HTTPException 沿用錯誤信封
        ("POST", "/tasks", {"name": "resize-images"}),  # 400：業務規則錯誤（名稱重複）
        ("POST", "/tasks", {"name": "encode-video", "priority": 2}),  # 200：建立成功
        ("GET", "/tasks/1/legacy", None),  # 500：回傳值違反 response_model，不輸出錯誤資料
    ]
    for method, url, body in cases:
        response = client.request(method, url, json=body)
        print(response.status_code, response.text)

    try:
        TestClient(app).get("/tasks/1/legacy")  # 預設 raise_server_exceptions=True
    except ResponseValidationError as exc:
        print(type(exc).__name__)  # 例外於送出 500 回應後重新拋出

    print(sorted(app.openapi()["paths"]["/tasks/{task_id}"]["get"]["responses"]))

# 預期輸出：
# 200 {"success":true,"code":200,"message":"OK","data":{"task_id":1,"name":"resize-images","status":"running","priority":3}}
# 400 {"success":false,"code":400,"message":"Request validation failed","errors":[{"field":"path.task_id","type":"greater_than_equal","message":"Input should be greater than or equal to 1"}]}
# 404 {"success":false,"code":404,"message":"Task 9 not found","errors":[{"field":null,"type":"http_error","message":"Task 9 not found"}]}
# 400 {"success":false,"code":400,"message":"Task name already exists","errors":[{"field":"body.name","type":"duplicate","message":"resize-images is already queued"}]}
# 200 {"success":true,"code":200,"message":"OK","data":{"task_id":2,"name":"encode-video","status":"pending","priority":2}}
# 500 {"success":false,"code":500,"message":"Internal Server Error","errors":[{"field":null,"type":"internal_error","message":"Internal Server Error"}]}
# ResponseValidationError
# ['200', '400', '4XX', '5XX']
