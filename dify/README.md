# Dify 工作流

`elder-guide.workflow.yml` 是一个 Dify **工作流应用**的 DSL，导入后即可在
「工作室 → 适老引导话术」中使用。

## 导入

Dify 界面：**工作室 → 创建应用 → 导入 DSL 文件** → 选择本目录的 yml。
也可以调 API：

```bash
curl -X POST http://127.0.0.1:8080/console/api/apps/imports \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: <csrf_token>" \
  -b cookies.txt \
  -d '{"mode":"yaml-content","yaml_content":"<yml 内容>"}'
```

## 结构

```
开始（query: text）
  → HTTP 节点  POST http://host.docker.internal:8765/api/steps
                body: {"query":"{{#start_node.query#}}"}
  → 结束（steps_raw = http_node.body）
```

HTTP 节点指向本机的 `/api/steps`（转发 Ollama），返回 `text/plain; charset=utf-8`，
这样 Dify 才不会把中文丢成 `?`。

## 集成时踩到的三个坑

1. **SSRF 拦截**：Dify 默认禁止 HTTP 节点访问内网地址，报
   `blocked by SSRF protection`。在 `docker/.env` 里加
   `SSRF_PROXY_ALLOW_PRIVATE_IPS=192.168.65.0/24,172.16.0.0/12,10.0.0.0/8` 后重建 api/worker。
2. **JSON body 格式**：HTTP 节点的 `body.type=json` 只允许**一个** item，
   整段 JSON 要作为这个 item 的 value（不是每个字段一个 item），否则报
   `json body type should have exactly one item`。
3. **中文乱码**：响应如果没有 `charset`，Dify 解码会丢字符。让被调用方返回
   `text/plain; charset=utf-8` 即可。

## 换成别的模型

把 HTTP 节点的 `url` 换成你的模型服务即可；也可以在 Dify 里配置 Ollama /
OpenAI 兼容的模型供应商，改成 LLM 节点（更"正规"，但要注意容器访问宿主机
`host.docker.internal` 的连通性）。
