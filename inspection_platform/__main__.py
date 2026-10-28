"""python -m inspection_platform — 启动平台 HTTP 服务（需已构建 static/ 或使用 webui dev 代理）。"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("inspection_platform.app.main:app", host="0.0.0.0", port=8001, reload=False)
