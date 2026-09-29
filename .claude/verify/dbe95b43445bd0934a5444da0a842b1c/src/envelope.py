"""envelope.py：常見回應格式之共用模組（成功 200／錯誤 400）。

執行：python envelope.py
相依：pip install "fastapi==0.141.1"
"""
from collections.abc import Mapping
from typing import Any, Generic, Literal, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """錯誤明細（errors[] 之單筆項目）。"""

    field: str | None = Field(default=None, description="錯誤位置，以 . 串接；非欄位錯誤為 null")
    type: str = Field(description="機器可讀之錯誤類型")
    message: str = Field(description="人類可讀之錯誤說明")


class SuccessResponse(BaseModel, Generic[T]):
    """成功回應信封（2xx）。"""

    success: Literal[True] = True
    code: int = Field(default=200, ge=200, le=299)
    message: str = "OK"
    data: T


class ErrorResponse(BaseModel):
    """錯誤回應信封（4xx／5xx）。"""

    success: Literal[False] = False
    code: int = Field(default=400, ge=400, le=599)
    message: str = "Bad Request"
    errors: list[ErrorDetail] = Field(min_length=1)


# 錯誤契約（僅用於 OpenAPI 文件，不參與執行期驗證）；宣告 4XX 後 FastAPI 不再自動加入 422 文件
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "Bad Request"},
    "4XX": {"model": ErrorResponse, "description": "Client Error"},
    "5XX": {"model": ErrorResponse, "description": "Server Error"},
}


class ApiError(Exception):
    """業務規則錯誤；由例外處理器轉換為錯誤信封。"""

    def __init__(
        self,
        message: str,
        errors: list[ErrorDetail] | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.errors = errors or [ErrorDetail(type="bad_request", message=message)]
        self.status_code = status_code


def ok(data: Any = None, *, message: str = "OK", code: int = 200) -> dict[str, Any]:
    """組裝成功信封；實際輸出結構由 response_model 驗證與過濾。"""
    return {"success": True, "code": code, "message": message, "data": data}


def error_response(
    status_code: int,
    message: str,
    errors: list[ErrorDetail],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """組裝錯誤信封；code 欄位等於 HTTP 狀態碼。"""
    body = ErrorResponse(code=status_code, message=message, errors=errors)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    """註冊全域例外處理器，使所有錯誤皆以錯誤信封輸出。"""

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return error_response(exc.status_code, exc.message, exc.errors)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 取代 FastAPI 預設之 422 {"detail": [...]}，統一為 400 錯誤信封
        errors = [
            ErrorDetail(
                field=".".join(str(part) for part in err["loc"]) or None,
                type=err["type"],
                message=err["msg"],
            )
            for err in exc.errors()
        ]
        return error_response(400, "Request validation failed", errors)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 註冊於 Starlette 之 HTTPException：涵蓋 FastAPI HTTPException 與 Starlette 路由產生之 404、405
        message = str(exc.detail)
        errors = [ErrorDetail(type="http_error", message=message)]
        return error_response(exc.status_code, message, errors, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 由 ServerErrorMiddleware 呼叫；送出此回應後例外仍重新拋出，供伺服器記錄
        errors = [ErrorDetail(type="internal_error", message="Internal Server Error")]
        return error_response(500, "Internal Server Error", errors)


if __name__ == "__main__":

    class TaskOut(BaseModel):
        task_id: int
        name: str
        status: str

    # 內部紀錄含 worker_token；以 SuccessResponse[TaskOut] 驗證後僅保留對外欄位
    record = {"task_id": 1, "name": "resize-images", "status": "running", "worker_token": "tkn-7f3a"}
    print(SuccessResponse[TaskOut].model_validate(ok(record)).model_dump_json())

    failure = ErrorResponse(
        errors=[
            ErrorDetail(
                field="body.priority",
                type="less_than_equal",
                message="Input should be less than or equal to 10",
            )
        ]
    )
    print(failure.model_dump_json())

# 預期輸出：
# {"success":true,"code":200,"message":"OK","data":{"task_id":1,"name":"resize-images","status":"running"}}
# {"success":false,"code":400,"message":"Bad Request","errors":[{"field":"body.priority","type":"less_than_equal","message":"Input should be less than or equal to 10"}]}
