#!/bin/bash
# 一条命令做完整回归（发版本前跑）：语法检查 → 演示模式界面 → 起测试环境 → 连后端的界面 → 文档页 → 帧数统计 → 停
# 用法：dev/check.sh        有任何一步不过，最后会列出来，退出码 1
DEV="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DEV")"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3
cd "$ROOT" || exit 2
BAD=()
step() { echo; echo "── $1"; shift; "$@" || BAD+=("$*"); }

if command -v ruff > /dev/null; then
  step "代码检查（ruff）" ruff check --isolated --select E9,F,W605 --line-length 200 app scripts dev
else
  step "语法检查" "$PY" -m compileall -q app scripts dev
fi
step "界面 · 演示模式" "$PY" dev/ui_smoke.py dev/.run/shots-demo --demo
step "重新自检窗口 · 演示模式" "$PY" dev/ui/recheck.py dev/.run/shots-demo --demo
step "起测试环境" "$DEV/serve.sh" start
step "界面 · 连后端" "$PY" dev/ui_smoke.py dev/.run/shots
step "说明页" "$PY" dev/ui/docs.py dev/.run/shots
step "说明页树状图" "$PY" dev/ui/tree.py dev/.run/shots
step "重新自检窗口 · 连后端" "$PY" dev/ui/recheck.py dev/.run/shots
step "整备自检和一键补齐的状态" "$PY" dev/test_checks.py
step "联网搜索和查说明书" "$PY" dev/test_search.py
step "更强的模型和换它重做" "$PY" dev/test_route.py
step "设置里的联网搜索" "$PY" dev/ui/search.py dev/.run/shots
step "对话页、Agent 状态、游戏内显示设置" "$PY" dev/ui/chat.py dev/.run/shots
step "一页一屏放下（不靠滚轮）" "$PY" dev/ui/fit.py dev/.run/shots
step "Kev 权重在不在本机" "$PY" dev/test_kev.py
step "游戏帧数统计" "$PY" dev/test_fps.py
step "游戏内显示的逻辑" "$PY" dev/test_osd.py
"$DEV/serve.sh" stop

echo
if [ ${#BAD[@]} -eq 0 ]; then echo "全部通过"; else echo "没通过的："; printf '  %s\n' "${BAD[@]}"; exit 1; fi
