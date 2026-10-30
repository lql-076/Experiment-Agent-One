#!/bin/bash
# 起 / 停测试环境（只在 Linux 沙箱里用，你的电脑上用不到）：
#   假服务（dev/mocks.py）：Kev 8091、假 DeepSeek 8099、假硬件监控 8085、假百炼语音合成 8097、假 API易 生图 8096；加 --with-model 再起假的本地模型服务 8090
#   测试后端（dev/test_backend.py）：8765，和真的一样，只是一键补齐的每一步换成假步骤
# 用法：dev/serve.sh start [--with-model] | stop | status
# 只按自己写下的 PID 文件停进程，不按名字杀。
DEV="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$DEV")"
RUN="$DEV/.run"
mkdir -p "$RUN"
PY="${PY:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY=python3

stop1() {
  if [ -f "$RUN/$1.pid" ]; then
    kill "$(cat "$RUN/$1.pid")" 2>/dev/null
    rm -f "$RUN/$1.pid"
  fi
}

case "$1" in
  start)
    stop1 backend; stop1 mocks
    rm -f "$RUN"/fake_*.flag
    MOCKARGS="--no-model"
    [ "$2" = "--with-model" ] && MOCKARGS=""
    nohup "$PY" "$DEV/mocks.py" $MOCKARGS > "$RUN/mocks.log" 2>&1 &
    echo $! > "$RUN/mocks.pid"
    sleep 1.5
    nohup "$PY" "$DEV/test_backend.py" > "$RUN/backend.log" 2>&1 &
    echo $! > "$RUN/backend.pid"
    for _ in $(seq 1 60); do
      curl -s http://127.0.0.1:8765/api/ping > /dev/null && break
      sleep 0.5
    done
    if ! curl -s http://127.0.0.1:8765/api/ping > /dev/null; then
      echo "后端没起来，看 $RUN/backend.log"; exit 1
    fi
    # 指向假服务，填一个假 Key（真 Key 永远不放进沙箱）
    curl -s -X PUT -H 'X-Agent: 1' -H 'Content-Type: application/json' http://127.0.0.1:8765/api/settings \
      -d '{"dsBase":"http://127.0.0.1:8099","hwUrl":"http://127.0.0.1:8085/data.json","blBase":"http://127.0.0.1:8097/api/v1","ttsEngine":"local","imgBase":"http://127.0.0.1:8096/v1","imgOut":"'"$RUN"'/生图输出-测试"}' > /dev/null
    curl -s -X PUT -H 'X-Agent: 1' -H 'Content-Type: application/json' http://127.0.0.1:8765/api/secrets \
      -d '{"k":"dsKey","v":"sk-test-0000"}' > /dev/null
    curl -s -X PUT -H 'X-Agent: 1' -H 'Content-Type: application/json' http://127.0.0.1:8765/api/secrets \
      -d '{"k":"blKey","v":"sk-test-0000"}' > /dev/null
    curl -s -X PUT -H 'X-Agent: 1' -H 'Content-Type: application/json' http://127.0.0.1:8765/api/secrets \
      -d '{"k":"imgKey","v":"sk-test-0000"}' > /dev/null
    echo "测试环境起来了：http://127.0.0.1:8765/   日志在 dev/.run/"
    ;;
  stop)
    stop1 backend; stop1 mocks
    echo "停了"
    ;;
  status)
    for n in mocks backend; do
      if [ -f "$RUN/$n.pid" ] && kill -0 "$(cat "$RUN/$n.pid")" 2>/dev/null; then echo "$n 在跑（PID $(cat "$RUN/$n.pid")）"; else echo "$n 没在跑"; fi
    done
    ;;
  *)
    echo "用法：dev/serve.sh start [--with-model] | stop | status"; exit 2
    ;;
esac
