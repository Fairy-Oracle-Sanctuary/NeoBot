# douyin2api 对接文档

- **服务地址**：`https://dy-api.d1ck.top`
- **API Key**：请向服务提供方申请，本文档不明文包含。

抖音（DouYin）分享链接解析 API。输入一条分享链接或分享文案，得到视频直连或图集与作者信息。

- 纯视频：返回去水印的 MP4 直连。
- 图集：返回每张静图直连。
- 支持 `v.douyin.com`（短链）、`www.douyin.com`、`www.iesdouyin.com`。
- `url` 字段可以直接传链接，也可以直接粘贴分享文案（会自动抽第一条抖音链接）。

> **不支持 LivePhoto 动图。** LivePhoto 帖会当作普通静图集返回，只包含每张静图的直连。

## 鉴权

除 `/health` 之外的所有端点都需要 API Key。二选一：

| 方式 | 请求头 |
| --- | --- |
| 自定义头 | `X-API-Key: <key>` |
| Bearer  | `Authorization: Bearer <key>` |

Key 未携带或不匹配一律返回 `401 UNAUTHORIZED`。

## 端点

### `GET /health`

存活探针，无需鉴权。

```
GET /health
→ 200 {"status": "ok"}
```

### `POST /api/parse`

解析一条抖音链接。

**请求**

```
POST /api/parse HTTP/1.1
Content-Type: application/json
X-API-Key: <key>

{
  "url": "https://v.douyin.com/iRxxxxx/"
}
```

`url` 也可以是完整分享文案，例如：

```json
{ "url": "5.79 abc:/ 复制打开抖音，看看...  https://v.douyin.com/iRxxxxx/" }
```

**响应 — 纯视频**

请求体示例：

```json
{ "url": "2.51 复制打开抖音，看看【炸洋芋研究生的作品】未烬之约！！啊啊啊，真的好喜欢# 兽人 # fur... https://v.douyin.com/foGOHAk0ckw/" }
```

响应：

```json
{
  "success": true,
  "data": {
    "type": "video",
    "title": "未烬之约！！啊啊啊，真的好喜欢#兽人 #furry兽人 #热门 #furry @抖音小助手",
    "author": "炸洋芋研究生",
    "author_uid": "MS4wLjABAAAAisjl7QL6DJqLz3rTZlYT5CewdaL_ke3nPMJ8tzSwZuzbrYl5LD5RUr-K7Ams9Ywm",
    "avatar_url": "https://p26.douyinpic.com/aweme/100x100/aweme-avatar/tos-cn-i-0813c000-ce_okErAq9EKdoEAUF90fIABAAeD2wf9Q4TABUEhD.jpeg?from=327834062",
    "cover_url": "https://p26-sign.douyinpic.com/tos-cn-p-0015c000-ce/oEDex7CkEiZ16KaE5O1AXBVCKIzBeqcPwAoi9e~tplv-dy-resize-walign-adapt-aq:720:q75.jpeg?lk3s=138a59ce&x-expires=1785646800&x-signature=J6a7VGHVGpemRxUgyxi%2Burb4h20%3D&...",
    "video_url": "https://v5-dy-ov-experiment.zjcdn.com/c8f3628e8f78ed7c1d414c72d3172e13/6a5c72cf/video/tos/cn/tos-cn-ve-15c000-ce/okHZcApfn8AZWIRUlrLeJCgQm5eYHQgg7GGuBx/?a=1128&ch=0&cr=0&dr=0&cd=0%7C0%7C0%7C0&cv=1&br=683&bt=683&..."
  }
}
```

**响应 — 图集**

请求体示例：

```json
{ "url": "4.17 08/17 A@g.bN xSY:/ :6pm 請給幸福和好运一點時間。# plog # infj # feelingmyworld # inmyfeeling  https://v.douyin.com/Mz1b0TIH5F8/" }
```

响应（`slides` 为节省篇幅只列出前两张，实际会返回全部）：

```json
{
  "success": true,
  "data": {
    "type": "gallery",
    "title": "請給幸福和好运一點時間。#plog #infj #feelingmyworld #inmyfeeling",
    "author": "Yoakim",
    "author_uid": "MS4wLjABAAAAstKyQZ09p81IuCsNW_RSD-k0NnLUSuGW9kWj__FOI8ILM8zEKgtCxtxpXZQ3dFwC",
    "avatar_url": "https://p11.douyinpic.com/aweme/100x100/aweme-avatar/tos-cn-i-0813c000-ce_ognpC02AEk2FgFfAFwFIuSzA99mCDEA4AfTQVn.jpeg?from=327834062",
    "cover_url": "https://p5-ex-gddgtc-sign.douyinpic.com/tos-cn-i-0813c000-ce/o0KZhqwfTEARHAkpA8AQQKITfUAE9EEeyD39iF~tplv-dy-resize-walign-adapt-aq:540:q75.jpeg?lk3s=138a59ce&x-expires=1785646800&x-signature=HUPyQ%2FXbndS2rSvEzZ0RqLnIt44%3D&...",
    "music_url": "https://sf6-cdn-tos.douyinstatic.com/obj/tos-cn-ve-2774/9897c2f96ed14cc3b961b955b01cccf4",
    "slides": [
      {
        "image_url": "https://p5-ex-gddgtc-sign.douyinpic.com/tos-cn-i-0813c000-ce/o0KZhqwfTEARHAkpA8AQQKITfUAE9EEeyD39iF~tplv-dy-lqen-new:1440:1440:q80.jpeg?lk3s=138a59ce&x-expires=1787029200&x-signature=KnKvzbG4aw41Lbpi6OYIN%2FxX%2Bm4%3D&..."
      },
      {
        "image_url": "https://p3-sign.douyinpic.com/tos-cn-i-0813c000-ce/oEAAEAQpeEKAA9rIUfJfEFliCD4pHZE3yRqTkw~tplv-dy-lqen-new:1440:1440:q80.jpeg?lk3s=138a59ce&x-expires=1787029200&x-signature=F3uDw9EPiD8RwNcz%2FmiSh6kyDZo%3D&..."
      }
    ]
  }
}
```

### `GET /api/parse`

同上，用 query string，方便浏览器 / curl 快速测：

```
GET /api/parse?url=https%3A%2F%2Fv.douyin.com%2FiRxxxxx%2F
X-API-Key: <key>
```

## 响应字段一览

| 字段 | 视频 | 图集 | 说明 |
| --- | :--: | :--: | --- |
| `type`        | ✓ | ✓ | `"video"` 或 `"gallery"` |
| `title`       | ✓ | ✓ | 帖子文案 |
| `author`      | ✓ | ✓ | 作者昵称 |
| `author_uid`  | ✓ | ✓ | 作者 `sec_uid` |
| `avatar_url`  | ✓ | ✓ | 作者头像 |
| `cover_url`   | ✓ | ✓ | 封面图（非 webp 优先） |
| `video_url`   | ✓ |   | 去水印 MP4 直连 |
| `music_url`   |   | ✓ | 背景音乐直连，可能为空字符串 |
| `slides`      |   | ✓ | 图集数组，见上例 |

所有直连都带有 DouYin 端的 `x-expires` 参数，通常数小时内有效。需要长期保存请自行下载。

## 错误格式

所有错误共用同一形状：

```json
{
  "success": false,
  "code": "PARSE_FAILED",
  "message": "解析失败，请稍后重试"
}
```

| HTTP | `code` | 场景 |
| --- | --- | --- |
| 400 | `BAD_REQUEST`    | 输入里没找到抖音链接、JSON 格式错误 |
| 401 | `UNAUTHORIZED`   | 缺 API Key 或 Key 错误 |
| 422 | `PARSE_FAILED`   | 链接有效但解析失败。见下方「PARSE_FAILED 的 message 内容」 |
| 500 | `INTERNAL`       | 服务内部错误 |

### `PARSE_FAILED` 的 `message` 内容

当 `code = PARSE_FAILED` 时，`message` 会尽量给出抖音端本身的原因，方便你在客户端上直接把原因展示给用户；如果拿不到具体原因（例如网络问题、我方内部错误），会退回到通用文案。

已知的抖音端原因示例（`message` 会直接是这段中文）：

| `message` | 场景 |
| --- | --- |
| `为尊重作者权限设置，需尝试在抖音内观看` | 作者开启了「仅限抖音 App 内观看」 |
| `作品不存在` / `视频不见了` / `内容不存在` | 帖子已被删除或下架 |
| `你所在的地区无法观看该内容` | 区域限制 |
| `解析失败，请稍后重试` | 通用兜底（拿不到抖音端具体原因时使用） |

抖音端原文可能随平台调整而变化，客户端不要按精确字符串硬匹配来做逻辑分支；如果需要区分，只判 `code` 即可，`message` 直接展示给用户。

## curl 速览

```bash
KEY=<your-api-key>
BASE=https://dy-api.d1ck.top

# POST，JSON body
curl -sS -X POST $BASE/api/parse \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $KEY" \
  -d '{"url":"https://v.douyin.com/iRxxxxx/"}' | jq

# GET，query string
curl -sS -G $BASE/api/parse \
  -H "X-API-Key: $KEY" \
  --data-urlencode "url=https://v.douyin.com/iRxxxxx/" | jq

# Bearer 也接受
curl -sS -X POST $BASE/api/parse \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"url":"5.79 abc:/ 复制打开抖音 https://v.douyin.com/iRxxxxx/"}' | jq
```

## 支持的链接形态

- `https://v.douyin.com/<id>/` — 短链（App 分享出来的）
- `https://www.douyin.com/video/<aweme_id>`
- `https://www.douyin.com/note/<aweme_id>` — 图集
- `https://www.iesdouyin.com/share/video/<aweme_id>/`
- `https://www.douyin.com/jingxuan?modal_id=<aweme_id>`

其他来源（例如西瓜视频 `ixigua.com`）不在支持范围内，会返回 `422 PARSE_FAILED`。
