# social-auto-upload（只拿了抖音那部分）

- 来源：https://github.com/dreammis/social-auto-upload ，提交 `3847fff`（2026-10-23）。
- 许可证：MIT（`LICENSE` 原样放着）。
- 拿了哪些（原样，一个字没改）：
  - `uploader/__init__.py`、`uploader/base_video.py`
  - `uploader/douyin_uploader/__init__.py`、`uploader/douyin_uploader/main.py`
  - `utils/__init__.py`、`utils/base_social_media.py`、`utils/log.py`、`utils/login_qrcode.py`、`utils/stealth.min.js`

## 为什么拷进来，不现下

作者家里连 GitHub 不稳。原项目的 `requirements.txt` 很大（Flask、biliup、opencv……），抖音这一块只要 `patchright` 和 `loguru`，这两个写进了 Agent 的 `requirements.txt`。

## Agent 怎么用它（`app/douyin_run.py`）

每次登录、检查、发布都单独起一个子进程（不弹黑窗口）跑 `app/douyin_run.py`。它在导入这里的代码之前先放好几样东西，所以这里的文件不用改：

1. 一个假的 `conf` 模块：
   - `BASE_DIR` 指到 `data\publish\run\`，原项目的日志、`cookies\`、`verify_code.txt` 都写在那里，不写进这个文件夹；`utils\stealth.min.js` 每次复制过去。
   - `LOCAL_CHROME_HEADLESS` 按 设置 › 发布 来。
2. 一个精简的 `utils.login_qrcode`：原来那个为了在终端里画二维码要装 opencv。我们的二维码直接显示在「发布」窗口里，用不上。
3. 改 patchright 的 `launch`：原项目写死 `channel="chromium"`，要另外下一个 Chromium。这里换成他电脑上已经有的 Chrome（没有就用 Edge），用的是临时的空白配置，不碰他自己的浏览器资料。
4. 接 loguru 的输出：每一行都转成「发布」窗口里的进展。看到要短信验证码时，窗口里弹一个框让他填（写进 `verify_code.txt`，原项目自己会读）。

## 抖音改版了怎么办

抖音创作者中心的页面一改，原项目就会跟着修。到时候把上面这几个文件换成新版的，`dev/test_publish.py` 里的自检会先查一遍导入和函数名对不对。
