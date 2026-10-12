# 配置认证与安全诊断

服务保留现有 Bearer 认证、Vision OCR、本地排版和可选 LLM 排版；不新增监听器或认证系统。

## 配置与恢复

- `AUTH_TOKEN` 必须从受限 `.env` 或既有受控环境明确配置；缺失、空值或示例值（含 `test`）拒绝启动。复制模板后须由操作者填入真实值，文件保持 `0600`、目录 `0700`、Git 忽略。不要把真实值放入命令行、URL、截图、文档或日志。
- 恢复既有加密备份中的配置时核对当前授权和客户端；不自动轮换 token，也不自动采用已撤销的旧值。认证比较使用常量时间比较；query 参数不能代替 Bearer header。
- `AUTH_TOKEN` 使用 `SecretStr`；内部消费者需要原值时调用 `get_secret_value()`。Settings 的 repr 隐藏 LLM 密钥与地址，启动配置错误只输出固定提示。不得输出 `model_dump()` 或 `ValidationError.errors()`，它们仍可能包含受限输入。
- `LLM_BASE_URL` 与 `LLM_API_KEY` 模板默认为空，按原可选配置启用；本地排版不依赖上游。LLM 授权恢复和独立周期巡检仍待操作者确认，并通过原 Hub/Pusher 统一事件通道落实；本补丁不探测真实提供方或新增登录流程。

## 日志和错误合同

请求日志只记录固定路由模板、允许的方法、状态码与耗时；未知路径记作 `<unmatched>`。Uvicorn access、httpx/httpcore 的原始 URL 日志关闭，Uvicorn 错误原文和 traceback 归为固定服务错误，`DEBUG` 不开放 HTTP traceback。

HTTP 错误保留状态码和现有响应结构：请求验证为固定 422，OCR 输入错误为固定 400，运行/未知错误为固定 500；不回传请求值、异常详情或图片正文。本地排版失败只返回固定分类，LLM HTTP 错误保留状态码，不输出提供方响应、密钥、URL 或原异常。成功识别及排版文本仍按原接口返回给已认证调用者。

`/health` 仍是现有公开接口并含系统信息，监听/CORS 边界及真实客户端连接另行验收。本补丁不改变授权范围或生产启动定义。

## 验证与发布

使用原 macOS venv 的 pytest/httpx/PyObjC 环境运行 `python -m pytest tests -q -p no:cacheprovider`。测试只使用合成密钥、图片、错误和内存 HTTP transport，不加载开发者 `.env` 或请求真实提供方。原生隔离验收应设置 QA 写入目录和 `OCR_QA_OUTSIDE_WRITE_PATH`，用 macOS sandbox 禁网及拒绝 QA 外写入；普通运行仅跳过此一项系统隔离检查。
