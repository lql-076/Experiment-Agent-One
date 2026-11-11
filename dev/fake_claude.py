"""测试用：假的 claude 命令行（v3.0，app/ccode.py）。照真的 `claude -p --output-format stream-json --verbose` 那样一行一个 JSON 往外吐。
从标准输入读要做的事，按里面的记号演：
  （默认）  开工 → 列待办（TodoWrite）→ 在当前文件夹写一个文件（真的写）→ 跑一条命令 → 勾完待办 → 结果
  【没登录】 往 stderr 写一句、退出码 1，不出结果
  【慢】     开工后一直等（测「停下」和超时）
  【被拒】   结果里带 2 个没被允许的动作
--version：打印版本号。把收到的参数和事情记在 dev/.run/fake_claude_last.json。"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

RUN = Path(__file__).resolve().parent / ".run"


def out(o):
    sys.stdout.write(json.dumps(o, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    a = sys.argv[1:]
    if "--version" in a:
        print("9.9.9 (Claude Code · 假的)")
        return 0
    prompt = sys.stdin.buffer.read().decode("utf-8")
    sid = a[a.index("--resume") + 1] if "--resume" in a else str(uuid.uuid4())
    RUN.mkdir(exist_ok=True)
    (RUN / "fake_claude_last.json").write_text(json.dumps({"argv": a, "prompt": prompt, "cwd": os.getcwd(), "session": sid, "resumed": "--resume" in a,
                                                            "path0": os.environ.get("PATH", "").split(os.pathsep)[0], "ws": os.environ.get("AGENT_WORKSPACE")},
                                                           ensure_ascii=False), "utf-8")
    if "【没登录】" in prompt:
        sys.stderr.write("Invalid API key · Please run /login\n")
        return 1
    out({"type": "system", "subtype": "init", "session_id": sid, "model": "deepseek-v4.1-flash", "cwd": os.getcwd(), "tools": ["Bash", "Write", "Edit", "TodoWrite"]})
    if "【慢】" in prompt:
        out({"type": "assistant", "message": {"content": [{"type": "text", "text": "这个要一会儿……"}]}, "session_id": sid, "parent_tool_use_id": None})
        time.sleep(120)
        return 0
    todo = lambda sts: {"type": "assistant", "session_id": sid, "parent_tool_use_id": None, "message": {"content": [{"type": "tool_use", "id": "t0", "name": "TodoWrite", "input": {"todos": [  # noqa: E731
        {"content": "写脚本", "status": sts[0], "activeForm": "正在写脚本"}, {"content": "运行看结果", "status": sts[1], "activeForm": "正在运行"}]}}]}}
    out(todo(["in_progress", "pending"]))
    d = Path("cc测试")
    d.mkdir(exist_ok=True)
    f = d / ("续.txt" if "--resume" in a else "hello.py")
    f.write_text("print('hi from claude code')\n", "utf-8")
    out({"type": "assistant", "session_id": sid, "parent_tool_use_id": None, "message": {"content": [
        {"type": "text", "text": "我先写个脚本。"}, {"type": "tool_use", "id": "t1", "name": "Write", "input": {"file_path": str(f.resolve()), "content": "print('hi')"}}]}})
    out({"type": "user", "session_id": sid, "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]}})
    out(todo(["completed", "in_progress"]))
    out({"type": "assistant", "session_id": sid, "parent_tool_use_id": None, "message": {"content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "python cc测试/hello.py"}}]}})
    out({"type": "user", "session_id": sid, "message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content": "hi from claude code", "is_error": "【出错】" in prompt}]}})
    out(todo(["completed", "completed"]))
    out({"type": "result", "subtype": "success", "is_error": False, "session_id": sid, "num_turns": 4, "total_cost_usd": 0.0123, "duration_ms": 900,
         "result": ("接着做完了：cc测试/续.txt" if "--resume" in a else "做完了：脚本在 cc测试/hello.py，运行输出 hi from claude code。"),
         "permission_denials": [{"tool_name": "Bash", "tool_input": {"command": "rm -rf x"}}] * 2 if "【被拒】" in prompt else []})
    return 0


if __name__ == "__main__":
    sys.exit(main())
