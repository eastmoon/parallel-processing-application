"""app_response_class.py：response_class 範本（原則 III，套用原則 I 之信封）。

執行：python app_response_class.py（與 envelope.py 置於同一目錄）
服務：uvicorn app_response_class:app --port 8000
相依：pip install "fastapi==0.141.1" httpx2 uvicorn
"""
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from envelope import ERROR_RESPONSES, SuccessResponse, register_exception_handlers


class EnvelopeJSONResponse(JSONResponse):
    """於渲染階段將回傳資料包裝為成功信封；僅用於 2xx 回應。"""

    def render(self, content: Any) -> bytes:
        # Starlette 於呼叫 render() 前已設定 self.status_code，code 與 HTTP 狀態碼同源
        envelope = {"success": True, "code": self.status_code, "message": "OK", "data": content}
        return super().render(envelope)


class TaskOut(BaseModel):
    """對外模型：作為 response_model，驗證與過濾內層資料。"""

    task_id: int
    name: str
    status: Literal["pending", "running", "done"]
    priority: int


TASKS: dict[int, dict[str, Any]] = {
    1: {"task_id": 1, "name": "resize-images", "status": "running", "priority": 3, "worker_token": "tkn-7f3a"},
}

app = FastAPI(title="response_class template")
register_exception_handlers(app)


@app.get(
    "/tasks/{task_id}",
    response_class=EnvelopeJSONResponse,  # 渲染：成功信封包裝
    response_model=TaskOut,  # 驗證與過濾：內層資料模型（不得宣告 SuccessResponse[TaskOut]，避免重複包裝）
    status_code=200,
    responses={
        200: {"model": SuccessResponse[TaskOut], "description": "OK"},  # 文件：實際輸出之信封結構
        **ERROR_RESPONSES,
    },
)
def get_task(task_id: Annotated[int, Path(ge=1)]) -> dict[str, Any]:
    record = TASKS.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return record  # 經 response_model 移除 worker_token、jsonable_encoder 轉換後，交由 render() 包裝


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    client = TestClient(app)
    for url in ("/tasks/1", "/tasks/0", "/tasks/9"):
        response = client.get(url)
        print(response.status_code, response.headers["content-type"], response.text)

    operation = app.openapi()["paths"]["/tasks/{task_id}"]["get"]
    print(operation["responses"]["200"]["content"])

# 預期輸出：
# 200 application/json {"success":true,"code":200,"message":"OK","data":{"task_id":1,"name":"resize-images","status":"running","priority":3}}
# 400 application/json {"success":false,"code":400,"message":"Request validation failed","errors":[{"field":"path.task_id","type":"greater_than_equal","message":"Input should be greater than or equal to 1"}]}
# 404 application/json {"success":false,"code":404,"message":"Task 9 not found","errors":[{"field":null,"type":"http_error","message":"Task 9 not found"}]}
# {'application/json': {'schema': {'$ref': '#/components/schemas/SuccessResponse_TaskOut_'}}}
