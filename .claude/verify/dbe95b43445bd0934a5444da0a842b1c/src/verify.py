"""verify.py：研究文件範例程式之驗證程式（Docker 實測）。

1. 以子行程執行各範例，逐行比對檔尾「# 預期輸出：」註解與實際標準輸出。
2. 以 TestClient 檢查範例未列印之鐵律（信封欄位、狀態碼、標頭、OpenAPI 文件）。
結束碼：0 表示全部通過；1 表示任一項失敗。執行紀錄寫入 out/。
"""
import json
import os
import platform
import subprocess
import sys
from importlib.metadata import distributions, version
from pathlib import Path
from typing import Any

SRC = Path(__file__).resolve().parent
OUT = SRC.parent / "out"
EXAMPLES = ("envelope.py", "app_response_model.py", "app_response_class.py", "app_selection.py")
MARKER = "# 預期輸出："
RESULTS: list[dict[str, Any]] = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "passed": bool(passed), "detail": detail})


def expected_output(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(MARKER) + 1
    return [line[2:] for line in lines[start:] if line.startswith("# ")]


def is_envelope(body: Any, success: bool) -> bool:
    """成功信封僅含 success/code/message/data；錯誤信封僅含 success/code/message/errors。"""
    if not isinstance(body, dict) or body.get("success") is not success:
        return False
    if success:
        return set(body) == {"success", "code", "message", "data"}
    return (
        set(body) == {"success", "code", "message", "errors"}
        and len(body["errors"]) >= 1
        and all(set(item) == {"field", "type", "message"} for item in body["errors"])
    )


def run_examples(log: list[str]) -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for name in EXAMPLES:
        proc = subprocess.run(
            [sys.executable, name],
            cwd=SRC,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
        actual = proc.stdout.splitlines()
        expected = expected_output(SRC / name)
        passed = proc.returncode == 0 and actual == expected
        detail = "" if passed else json.dumps(
            {"returncode": proc.returncode, "expected": expected, "actual": actual, "stderr": proc.stderr[-4000:]},
            ensure_ascii=False,
            indent=2,
        )
        record(f"example {name}: output matches expected", passed, detail)
        record(f"example {name}: no stderr output (warnings)", proc.stderr == "", proc.stderr[-4000:])
        log.append(f"===== {name} (returncode={proc.returncode}) =====\n{proc.stdout}")
        if proc.stderr:
            log.append(f"----- {name} stderr -----\n{proc.stderr}")


def check_envelope() -> None:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from envelope import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    def boom() -> dict[str, str]:
        raise RuntimeError("db password=secret at /srv/app/db.py")

    @app.get("/auth")
    def auth() -> dict[str, str]:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom")
    record(
        "I: unexpected exception -> 500 envelope without internal details",
        r.status_code == 500 and is_envelope(r.json(), False) and r.json()["code"] == 500 and "secret" not in r.text,
        f"{r.status_code} {r.text}",
    )
    r = client.get("/auth")
    record(
        "I: HTTPException keeps headers in error envelope",
        r.status_code == 401 and r.headers.get("www-authenticate") == "Bearer" and is_envelope(r.json(), False),
        f"{r.status_code} {dict(r.headers)} {r.text}",
    )
    try:
        TestClient(app).get("/boom")
        reraised = False
    except RuntimeError:
        reraised = True
    record("I: exception re-raised after the 500 response is sent", reraised)


def check_response_model() -> None:
    from fastapi.testclient import TestClient

    import app_response_model as m

    client = TestClient(m.app, raise_server_exceptions=False)
    r = client.get("/tasks/1")
    record(
        "II: 200 application/json success envelope without internal field",
        r.status_code == 200
        and r.headers["content-type"] == "application/json"
        and "worker_token" not in r.text
        and is_envelope(r.json(), True),
        f"{r.headers.get('content-type')} {r.text}",
    )
    r = client.delete("/tasks/1")
    record(
        "II: Starlette 405 uses error envelope and keeps Allow header",
        r.status_code == 405 and r.headers.get("allow") == "GET" and is_envelope(r.json(), False) and r.json()["code"] == 405,
        f"{r.status_code} {r.headers.get('allow')} {r.text}",
    )
    r = client.get("/no-such-path")
    record(
        "II: Starlette 404 uses error envelope",
        r.status_code == 404 and is_envelope(r.json(), False) and r.json()["message"] == "Not Found",
        r.text,
    )
    r = client.post("/tasks", json={"name": ""})
    body = r.json()
    record(
        "II: request body validation error -> 400 envelope",
        r.status_code == 400
        and is_envelope(body, False)
        and body["errors"][0]["field"] == "body.name"
        and body["errors"][0]["type"] == "string_too_short",
        r.text,
    )
    r = client.post("/tasks", content=b"{bad json", headers={"content-type": "application/json"})
    record(
        "II: invalid JSON body -> 400 envelope",
        r.status_code == 400 and is_envelope(r.json(), False) and r.json()["errors"][0]["type"] == "json_invalid",
        r.text,
    )
    responses = m.app.openapi()["paths"]["/tasks/{task_id}"]["get"]["responses"]
    record(
        "II: OpenAPI 200 schema is SuccessResponse[TaskOut]",
        responses["200"]["content"]["application/json"]["schema"]
        == {"$ref": "#/components/schemas/SuccessResponse_TaskOut_"},
        json.dumps(responses.get("200"), ensure_ascii=False),
    )
    record(
        "II: OpenAPI 400/4XX/5XX schema is ErrorResponse",
        all(
            responses[key]["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/ErrorResponse"}
            for key in ("400", "4XX", "5XX")
        ),
        json.dumps(responses, ensure_ascii=False),
    )
    record("II: no automatic 422 document when 4XX is declared", "422" not in responses, str(sorted(responses)))


def check_response_class() -> None:
    from fastapi.testclient import TestClient

    import app_response_class as c

    client = TestClient(c.app)
    r = client.get("/tasks/1")
    record(
        "III: envelope class wraps data filtered by response_model",
        r.status_code == 200 and is_envelope(r.json(), True) and "worker_token" not in r.text,
        r.text,
    )
    rendered = c.EnvelopeJSONResponse({"task_id": 1}, status_code=201)
    record(
        "III: render() takes code from status_code",
        json.loads(rendered.body)["code"] == 201,
        rendered.body.decode("utf-8"),
    )


def check_selection() -> None:
    from fastapi.testclient import TestClient

    import app_selection as s

    client = TestClient(s.app)
    r = client.get("/tasks/1")
    record(
        "IV-A: header set through injected Response",
        r.headers.get("cache-control") == "no-store" and is_envelope(r.json(), True),
        str(dict(r.headers)),
    )
    r = client.get("/tasks/1/log")
    record(
        "IV-B: text/plain body is not enveloped",
        r.headers["content-type"] == "text/plain; charset=utf-8" and r.text == "resized 120/300 images",
        r.text,
    )
    r = client.get("/tasks/0/log")
    record(
        "IV-B: validation error on text route is JSON 400 envelope",
        r.status_code == 400 and r.headers["content-type"] == "application/json" and is_envelope(r.json(), False),
        f"{r.status_code} {r.headers.get('content-type')} {r.text}",
    )
    paths = s.app.openapi()["paths"]
    c_200 = paths["/tasks"]["get"]["responses"]["200"]["content"]
    record(
        "IV-C: OpenAPI 200 schema is SuccessResponse[TaskPage]",
        c_200 == {"application/json": {"schema": {"$ref": "#/components/schemas/SuccessResponse_TaskPage_"}}},
        json.dumps(c_200, ensure_ascii=False),
    )
    b_responses = paths["/tasks/{task_id}/log"]["get"]["responses"]
    record(
        "IV-B: OpenAPI 200 media type is text/plain",
        list(b_responses["200"]["content"]) == ["text/plain"],
        json.dumps(b_responses, ensure_ascii=False),
    )
    record(
        "IV-B: automatic 422 document exists when 4XX is not declared",
        "422" in b_responses,
        str(sorted(b_responses)),
    )


def check_fastapi_defaults() -> None:
    from typing import Annotated

    from fastapi import FastAPI, Path
    from fastapi.testclient import TestClient

    from envelope import ErrorResponse

    app = FastAPI()  # 未註冊原則 I 之例外處理器

    @app.get("/only-400/{item_id}", responses={400: {"model": ErrorResponse}})
    def only_400(item_id: Annotated[int, Path(ge=1)]) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/only-4xx/{item_id}", responses={"4XX": {"model": ErrorResponse}})
    def only_4xx(item_id: Annotated[int, Path(ge=1)]) -> dict[str, int]:
        return {"item_id": item_id}

    r = TestClient(app).get("/only-400/0")
    record(
        "default: FastAPI request validation error is 422 with {'detail': [...]}",
        r.status_code == 422 and set(r.json()) == {"detail"} and isinstance(r.json()["detail"], list),
        f"{r.status_code} {r.text}",
    )
    paths = app.openapi()["paths"]
    only_400_responses = paths["/only-400/{item_id}"]["get"]["responses"]
    only_4xx_responses = paths["/only-4xx/{item_id}"]["get"]["responses"]
    record(
        "default: declaring only 400 keeps the automatic 422 document",
        "422" in only_400_responses,
        str(sorted(only_400_responses)),
    )
    record(
        "default: declaring 4XX omits the automatic 422 document",
        "422" not in only_4xx_responses,
        str(sorted(only_4xx_responses)),
    )


def check_uvicorn_serving() -> None:
    import time
    import urllib.request

    # 範例之「服務」指令：uvicorn app_response_model:app --port 8000
    proc = subprocess.Popen(
        ["uvicorn", "app_response_model:app", "--port", "8000"],
        cwd=SRC,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    status, body = None, None
    try:
        for _ in range(100):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8000/tasks/1", timeout=1) as resp:
                    status, body = resp.status, json.loads(resp.read())
                break
            except OSError:
                time.sleep(0.2)
    finally:
        proc.terminate()
        server_log = proc.communicate(timeout=10)[0]
    record(
        "serve: uvicorn app_response_model:app returns success envelope",
        status == 200 and is_envelope(body, True),
        f"{status} {body}\n{server_log[-2000:]}",
    )


def main() -> int:
    OUT.mkdir(exist_ok=True)
    packages = {
        name: version(name) for name in ("fastapi", "pydantic", "pydantic-core", "starlette", "httpx2", "uvicorn")
    }
    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": packages,
        "installed": sorted(f"{dist.metadata['Name']}=={dist.version}" for dist in distributions()),
    }
    log: list[str] = []
    run_examples(log)
    checks = (
        check_envelope,
        check_response_model,
        check_response_class,
        check_selection,
        check_fastapi_defaults,
        check_uvicorn_serving,
    )
    for check in checks:
        try:
            check()
        except Exception as exc:  # 檢查程式本身發生例外亦視為驗證失敗
            record(f"{check.__name__} raised", False, repr(exc))

    (OUT / "environment.json").write_text(json.dumps(environment, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "results.json").write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "examples.log").write_text("\n".join(log), encoding="utf-8")

    failed = [item for item in RESULTS if not item["passed"]]
    print(json.dumps({"python": environment["python"], **packages}))
    for item in RESULTS:
        print("PASS" if item["passed"] else "FAIL", item["name"])
        if not item["passed"]:
            print(item["detail"])
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
